"""Validation gates: the screening ladder's own rules and the writes they guard.

Every outcome asserted here is derived from the fixed ranking of PRD §2.9, the
ladder narrative of PRD §3.6, the label-time re-verification and scan rules of
PRD §3.7, the carrier chain of PRD §3.3, the prohibited-ZIP rules of PRD §3.1 and
the club-run dating rule of PRD §3.8.

Screening never answers with an error envelope (PRD §2.9), so a refused screen is
read off the returned order's ``compliance_status`` and ``rejection_error_id``,
while the same identifiers are asserted as real HTTP errors at the guarded writes.

The harness restarts the server and empties the database before every test, so
each test stands its own landscape up from scratch.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import CLOCK_DEFAULT_CANONICAL
from test_helpers.test_users import CARRIER, OFFICER_A

# One 750 ml bottle at 4200 c: 0.750 L, and 35 cents of TX excise after the
# small-producer credit of PRD §3.5.
ONE_BOTTLE = [f.order_line(bottles=1)]
ONE_BOTTLE_EXCISE_CENTS = 35


def _ledger_rows(api, **filters):
    """The append-only ledger rows matching the given filters (PRD §3.4)."""
    params = dict(filters)
    params.setdefault("limit", 100)
    return get_success_data(api.list_volume_ledger_entries(OFFICER_A, params))


# ---------------------------------------------------------------------------
# The age gate: the birthday itself completes the year
# ---------------------------------------------------------------------------
def _build_birthday_edge(api):
    """Two verified buyers one day apart across a 21st birthday on the clock."""
    scape = fx.build_landscape(api, consumer_overrides={"birthdate": "2005-08-01"})
    one_day_short = fx.create_verified_consumer(
        api,
        full_name="Zed Buyer",
        email="zed@example.com",
        birthdate="2005-08-02",
        address_line="14 Vine St",
    )
    exactly_21 = scape.create_order(lines=ONE_BOTTLE)
    still_20 = scape.create_order(lines=ONE_BOTTLE, consumer_id=one_day_short["id"])
    return {
        "scape": scape,
        "exactly_21": scape.screen(exactly_21["id"]),
        "still_20": scape.screen(still_20["id"]),
    }


def test_underage_check_counts_the_birthday_itself(api):
    """Born on the clock date's anniversary clears; one day later is refused.

    "The age gate is evaluated separately and against the destination state's own
    threshold: the consumer's completed whole years between `birthdate` and the
    logical clock date, computed as calendar anniversaries with the birthday itself
    counting as the day the year completes, must be at least the state rule's
    `min_purchaser_age`; falling short records `ERR_CONSUMER_UNDERAGE`." (PRD 3.4)

    "**The purchaser must be old enough.** Completed whole years from `birthdate`
    to the logical clock date, counted by calendar anniversary, must be at least
    the state's `min_purchaser_age`; otherwise `ERR_CONSUMER_UNDERAGE`." (PRD 3.6)

    "**Screening never returns an error envelope.** It always answers HTTP 200
    with the order body, and the outcome is expressed by moving the order's
    compliance dimension and writing the identifier of the *first* — that is, the
    highest-ranked — failing ladder rule into the order's `rejection_error_id`."
    (PRD 2.9)

    "If the highest-ranked failing check is not one of the three overridable ones,
    the order is rejected and — since `REJECTED` is terminal on the compliance
    axis — the order is finished." (PRD 3.6)

    Design: Corner/validations/underage_check_counts_the_birthday_itself
    """
    built = _build_birthday_edge(api)

    a.assert_order_dimensions(built["exactly_21"], compliance_status="CLEARED")
    a.assert_rejection(built["exactly_21"], None)

    # ERR_CONSUMER_UNDERAGE is not one of the three overridable rules.
    a.assert_order_dimensions(built["still_20"], compliance_status="REJECTED")
    a.assert_rejection(built["still_20"], "ERR_CONSUMER_UNDERAGE")


def test_an_underage_refusal_reserves_no_liters_and_accrues_no_excise(api):
    """The rejected order leaves the ledger and the winery counter alone.

    "A **`DRAFT` → `REJECTED`** outcome writes the failing identifier into
    `rejection_error_id` and does nothing else: no ledger entry is appended, and
    `Winery.excise_accrued_cents` is untouched." (PRD 3.6)

    "It appends a volume-ledger entry with `event_type` `SHIPMENT_ACCEPTED`,
    `liters` equal to positive `total_liters`, `occurred_at` at the logical clock,
    `order_id` pointing at the order, `shipment_id` null, and `state_code` equal to
    the order's `ship_to_state_code`." (PRD 3.6)

    "The order must be `CLEARED` on the compliance axis and either `UNFULFILLED`
    or — for a re-ship — `RETURNED` on the fulfillment axis; any other combination
    is refused with `ERR_ORDER_NOT_CLEARED` (HTTP 409)." (PRD 3.7)

    Design: Corner/validations/underage_check_counts_the_birthday_itself
    """
    built = _build_birthday_edge(api)
    scape = built["scape"]

    assert _ledger_rows(api, order_id=built["still_20"]["id"]) == []
    cleared_rows = _ledger_rows(api, order_id=built["exactly_21"]["id"])
    assert len(cleared_rows) == 1
    a.assert_ledger_entry(
        cleared_rows[0], event_type="SHIPMENT_ACCEPTED", liters=0.750, state_code="TX",
        order_id=built["exactly_21"]["id"],
    )

    # Only the cleared order accrued excise.
    winery = scape.read_winery()
    a.assert_cents(
        winery["excise_accrued_cents"], ONE_BOTTLE_EXCISE_CENTS, "excise_accrued_cents"
    )

    # The state-transition band of PRD §2.9 answers before the age rule can be
    # re-raised at label time.
    refused_label = api.create_shipment(
        f.shipment_payload(built["still_20"]["id"], scape.enrollment_id),
        scape.operator,
    )
    validate_error(refused_label, "ERR_ORDER_NOT_CLEARED", 409)
    shipments, _meta = validate_paginated(
        api.list_shipments(OFFICER_A, {"order_id": built["still_20"]["id"]})
    )
    assert shipments == []


# ---------------------------------------------------------------------------
# The identity gate, shown failing and then passing
# ---------------------------------------------------------------------------
def test_unverified_consumer_is_blocked_until_id_verification_lands(api):
    """One id-verification call is the only difference between the two screens.

    "Identity verification is a `ComplianceOfficer` act. The officer records the
    method used — `id_verification_method` set to `DOCUMENT` or `DATABASE`, the
    third declared value `NONE` being the unverified starting state — and the
    system stamps `id_verified_at` from the logical clock and increments
    `Consumer.version`. Until `id_verified_at` is non-null, screening records
    `ERR_ID_VERIFICATION_REQUIRED` against any order for that consumer." (PRD 3.4)

    "**The purchaser's identity must be verified.** `id_verified_at` must be
    non-null; otherwise `ERR_ID_VERIFICATION_REQUIRED`." (PRD 3.6)

    "`compliance_status` answers the licensing question and takes one of `DRAFT`,
    `CLEARED`, `REJECTED`, `OVERRIDE_PENDING` or `SUSPENDED_PERMIT`; it begins at
    `DRAFT` and `REJECTED` is its only terminal value." (PRD 2.11)

    Design: Corner/validations/unverified_consumer_is_blocked_until_id_verification_lands
    """
    scape = fx.build_landscape(api, verify_consumer_id=False)

    before_verification = scape.create_order(lines=ONE_BOTTLE)
    refused = scape.screen(before_verification["id"])
    a.assert_order_dimensions(refused, compliance_status="REJECTED")
    a.assert_rejection(refused, "ERR_ID_VERIFICATION_REQUIRED")

    version_before = scape.consumer_version()
    verified = fx.verify_consumer(api, scape.consumer_id)
    assert verified["id_verification_method"] == "DOCUMENT"
    a.assert_instant_equals(verified["id_verified_at"], CLOCK_DEFAULT_CANONICAL)
    assert verified["version"] == version_before + 1

    after_verification = scape.create_order(lines=ONE_BOTTLE)
    cleared = scape.screen(after_verification["id"])
    a.assert_order_dimensions(cleared, compliance_status="CLEARED")
    a.assert_rejection(cleared, None)

    # Verifying the consumer does not retroactively clear the earlier refusal.
    a.assert_order_dimensions(
        scape.read_order(before_verification["id"]), compliance_status="REJECTED"
    )

    rows = _ledger_rows(api, consumer_id=scape.consumer_id)
    assert len(rows) == 1
    a.assert_ledger_entry(
        rows[0], event_type="SHIPMENT_ACCEPTED", liters=0.750,
        order_id=after_verification["id"],
    )


# ---------------------------------------------------------------------------
# A state that forbids DTC outranks the permit question
# ---------------------------------------------------------------------------
def test_a_state_that_forbids_dtc_blocks_the_order_before_any_permit_question(api):
    """No UT permit exists either, and the state rule still wins the ranking.

    "**The state must allow direct shipment.** If the governing state rule's
    `allows_dtc` is false, the recorded outcome is `ERR_STATE_DTC_PROHIBITED`."
    (PRD 3.6)

    "Within that final band of domain rules there is a further fixed ranking, and
    each rule below is listed in the order it is evaluated whenever more than one
    of them applies to the same request:" (PRD 2.9)

    "1. the destination state permits direct-to-consumer wine shipment at all —
    `ERR_STATE_DTC_PROHIBITED`;" (PRD 2.9)

    "5. the winery holds some permit for the destination state —
    `ERR_PERMIT_MISSING_FOR_STATE`;" (PRD 2.9)

    "The default address is a convenience, not a constraint — an order may ship to
    a different state entirely, and the state rule that governs an order is chosen
    by the order's own destination, not by the consumer's home state." (PRD 3.4)

    "The order must be `CLEARED` on the compliance axis and either `UNFULFILLED`
    or — for a re-ship — `RETURNED` on the fulfillment axis; any other combination
    is refused with `ERR_ORDER_NOT_CLEARED` (HTTP 409)." (PRD 3.7)

    Design: Corner/validations/a_state_that_forbids_dtc_blocks_the_order_before_any_permit_question
    """
    scape = fx.build_landscape(api)
    fx.create_state_rule(api, state_code="UT", allows_dtc=False)

    tx_control = scape.screen(scape.create_order(lines=ONE_BOTTLE)["id"])
    forbidden = scape.screen(
        scape.create_order(
            lines=ONE_BOTTLE, ship_to_state_code="UT", ship_to_zip="84101"
        )["id"]
    )

    a.assert_order_dimensions(tx_control, compliance_status="CLEARED")
    a.assert_order_dimensions(forbidden, compliance_status="REJECTED")
    # The winery holds no UT permit at all, yet rule 1 answers before rule 5.
    a.assert_rejection(forbidden, "ERR_STATE_DTC_PROHIBITED")

    # A UT state rule does exist, so this is a business refusal and not a lookup
    # failure.
    refused_label = api.create_shipment(
        f.shipment_payload(forbidden["id"], scape.enrollment_id), scape.operator
    )
    validate_error(refused_label, "ERR_ORDER_NOT_CLEARED", 409)
    shipments, _meta = validate_paginated(
        api.list_shipments(OFFICER_A, {"order_id": forbidden["id"]})
    )
    assert shipments == []

    winery = scape.read_winery()
    a.assert_cents(
        winery["excise_accrued_cents"], ONE_BOTTLE_EXCISE_CENTS, "excise_accrued_cents"
    )


# ---------------------------------------------------------------------------
# Prohibited ZIPs: the effective date and the uniqueness key
# ---------------------------------------------------------------------------
def test_a_future_dated_prohibited_zip_is_ignored_until_it_takes_effect(api):
    """The same row is invisible at screening and decisive at label time.

    "**The destination ZIP must not be blocked.** A prohibited-ZIP row of the
    destination state matches when its `zip_code` equals the order's `ship_to_zip`
    and its `effective_from` falls on or before the logical clock date; any
    `reason` value blocks, `DRY_COUNTY` included. A matching row records
    `ERR_PROHIBITED_DESTINATION`. Rows whose `effective_from` is strictly after the
    clock date are ignored." (PRD 3.6)

    "Screening honours a block only when its `effective_from` falls on or before
    the logical clock date; a block dated strictly after the clock date is ignored
    entirely, which is what lets a state pre-announce a block for a future date."
    (PRD 3.1)

    "Beyond those preconditions, label production **re-verifies the safety, permit
    and carrier gates of the screening ladder and raises them as genuine HTTP
    errors** rather than recording them." (PRD 3.7)

    "Any of `ERR_STATE_DTC_PROHIBITED`, `ERR_PROHIBITED_DESTINATION`,
    `ERR_CONSUMER_UNDERAGE`, `ERR_ID_VERIFICATION_REQUIRED`,
    `ERR_PERMIT_MISSING_FOR_STATE`, `ERR_PERMIT_NOT_ACTIVE`, `ERR_PERMIT_EXPIRED`,
    `ERR_CARRIER_NOT_ENROLLED` or `ERR_ADULT_SIGNATURE_NOT_SUPPORTED` may come back
    as an HTTP 422 error at this point, and the most common reason is elapsed time:
    the prohibited-ZIP list may have grown since the order cleared, and the permit
    may have lapsed." (PRD 3.7)

    Design: Corner/validations/a_future_dated_prohibited_zip_is_ignored_until_it_takes_effect
    """
    scape = fx.build_landscape(api)
    fx.create_prohibited_zip(
        api, scape.state_rule_id, zip_code="78701", reason="DRY_COUNTY",
        effective_from="2026-09-01",
    )
    fx.create_prohibited_zip(
        api, scape.state_rule_id, zip_code="78702",
        reason="PROHIBITED_MUNICIPALITY", effective_from="2026-07-01",
    )

    # 2026-09-01 is strictly after the 2026-08-01 clock, so the 78701 row is not
    # yet in force.
    cleared = scape.screen(scape.create_order(lines=ONE_BOTTLE)["id"])
    a.assert_order_dimensions(cleared, compliance_status="CLEARED")
    a.assert_rejection(cleared, None)

    blocked = scape.screen(
        scape.create_order(lines=ONE_BOTTLE, ship_to_zip="78702")["id"]
    )
    a.assert_order_dimensions(blocked, compliance_status="REJECTED")
    a.assert_rejection(blocked, "ERR_PROHIBITED_DESTINATION")

    # The block takes effect between clearance and shipping.
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    refused_label = api.create_shipment(
        f.shipment_payload(cleared["id"], scape.enrollment_id), scape.operator
    )
    validate_error(refused_label, "ERR_PROHIBITED_DESTINATION", 422)

    # The refusal rewrites nothing that clearance froze.
    still_cleared = scape.read_order(cleared["id"])
    a.assert_order_dimensions(
        still_cleared, compliance_status="CLEARED", fulfillment_status="UNFULFILLED"
    )
    rows = _ledger_rows(api, order_id=cleared["id"])
    assert len(rows) == 1
    a.assert_ledger_entry(rows[0], event_type="SHIPMENT_ACCEPTED", liters=0.750)
    shipments, _meta = validate_paginated(
        api.list_shipments(OFFICER_A, {"order_id": cleared["id"]})
    )
    assert shipments == []


def test_prohibited_zip_uniqueness_is_scoped_to_its_state_rule(api):
    """The key is the state rule and the ZIP, and nothing else.

    "The pair of `state_rule_id` and `zip_code` must be unique — a repeat
    declaration is refused with `ERR_DUPLICATE_PROHIBITED_ZIP` (HTTP 409)."
    (PRD 3.1)

    "They are enumerated as **prohibited ZIPs** hung beneath a state rule by either
    a `PlatformAdmin` or a `ComplianceOfficer`, each carrying the owning
    `state_rule_id`, a `zip_code` of exactly five digits, a `reason` drawn from
    `DRY_COUNTY`, `PROHIBITED_MUNICIPALITY`, `PO_BOX_ONLY` or `CARRIER_UNSERVED`,
    and an `effective_from` date." (PRD 3.1)

    "A prohibited-ZIP row is immutable once appended: there is no update operation,
    no withdrawal, and no `version` on the row." (PRD 3.1)

    "The reverse lookup of every ZIP declared under a state rule can be filtered by
    `reason`." (PRD 3.1)

    Design: Corner/validations/prohibited_zip_uniqueness_is_scoped_to_its_state_rule
    """
    fx.set_clock(api)
    texas = fx.create_state_rule(api)
    nevada = fx.create_state_rule(api, state_code="NV")
    fx.create_prohibited_zip(
        api, texas["id"], zip_code="89101", reason="DRY_COUNTY",
        effective_from="2026-07-01",
    )

    exact_repeat = api.create_prohibited_zip(
        texas["id"],
        f.prohibited_zip_payload(
            zip_code="89101", reason="DRY_COUNTY", effective_from="2026-07-01"
        ),
        OFFICER_A,
    )
    validate_error(exact_repeat, "ERR_DUPLICATE_PROHIBITED_ZIP", 409)

    # Neither reason nor effective_from is part of the key.
    same_zip_new_reason = api.create_prohibited_zip(
        texas["id"],
        f.prohibited_zip_payload(
            zip_code="89101", reason="PO_BOX_ONLY", effective_from="2026-10-01"
        ),
        OFFICER_A,
    )
    validate_error(same_zip_new_reason, "ERR_DUPLICATE_PROHIBITED_ZIP", 409)

    # The very same ZIP under a different state rule is a different pair.
    accepted = get_success_data(
        api.create_prohibited_zip(
            nevada["id"],
            f.prohibited_zip_payload(
                zip_code="89101", reason="CARRIER_UNSERVED",
                effective_from="2026-07-01",
            ),
            OFFICER_A,
        ),
        201,
    )
    assert accepted["state_rule_id"] == nevada["id"]
    assert accepted["zip_code"] == "89101"
    assert accepted["reason"] == "CARRIER_UNSERVED"
    a.assert_immutable_identity(accepted)

    # Neither refused write mutated the incumbent row.
    tx_rows, _tx_meta = validate_paginated(
        api.list_prohibited_zips(texas["id"], OFFICER_A, {"limit": 100})
    )
    assert len(tx_rows) == 1
    assert tx_rows[0]["reason"] == "DRY_COUNTY"
    assert tx_rows[0]["effective_from"] == "2026-07-01"

    nv_rows, _nv_meta = validate_paginated(
        api.list_prohibited_zips(nevada["id"], OFFICER_A, {"limit": 100})
    )
    assert len(nv_rows) == 1

    filtered, _f_meta = validate_paginated(
        api.list_prohibited_zips(texas["id"], OFFICER_A, {"reason": "PO_BOX_ONLY"})
    )
    assert filtered == []


# ---------------------------------------------------------------------------
# The club run's dating rule is inclusive at the clock date
# ---------------------------------------------------------------------------
def _build_due_subscription(api):
    """One MONTHLY subscription that has been due since 2026-07-15."""
    scape = fx.build_landscape(api)
    subscription = scape.create_subscription(next_run_date="2026-07-15")
    return scape, subscription


def _winery_orders(api, winery_id):
    orders, _meta = validate_paginated(
        api.list_orders(OFFICER_A, {"winery_id": winery_id, "limit": 100})
    )
    return orders


def test_club_run_dated_one_day_past_the_clock_is_refused_and_changes_nothing(api):
    """A future run_date is a real error, and the refusal is inert.

    "The **club run** is the scheduler, invoked by a `WineryOperator` or a
    `ComplianceOfficer` for one `winery_id` on one `run_date`. The `run_date` must
    fall on or before the logical clock date; a run dated in the future is refused
    with `ERR_RUN_DATE_IN_FUTURE` (HTTP 422)." (PRD 3.8)

    "It also names `next_run_date`, the date on or before which the next run should
    generate an order — supplied at creation as the first scheduled run and advanced
    by the system after every successful run — and `annual_allotment`, the number of
    shipments of at least 1 that the member has prepaid for the year." (PRD 3.8)

    Design: Corner/validations/club_run_date_may_equal_the_clock_but_never_exceed_it
    """
    scape, subscription = _build_due_subscription(api)

    refused = api.create_club_run(
        f.club_run_payload(scape.winery_id, "2026-08-02"), scape.operator
    )
    validate_error(refused, "ERR_RUN_DATE_IN_FUTURE", 422)

    untouched = scape.read_subscription(subscription["id"])
    assert untouched["next_run_date"] == "2026-07-15"
    assert untouched["consumed_shipments"] == 0
    assert untouched["missed_run_count"] == 0
    assert untouched["status"] == "ACTIVE"
    assert _winery_orders(api, scape.winery_id) == []


def test_a_back_dated_club_run_generates_the_discounted_order_and_advances_the_schedule(
    api,
):
    """An earlier run_date is legal, and the next run then finds nothing to do.

    "For each processed subscription the run creates an order for that
    subscription's consumer and winery with `club_subscription_id` set, with
    `ship_to_address_line`, `ship_to_state_code` and `ship_to_zip` copied from the
    consumer's default address, and with exactly **one** line built from the
    subscription template — its `sku`, its `bottle_ml`, a `bottles` count equal to
    `bottles_per_shipment`, and its `unit_price_cents`. The full twelve-step charge
    chain of §3.5 runs on that order, including the club shipping discount, since
    the order carries a `club_subscription_id`." (PRD 3.8)

    "`shipping_discount_cents` is the wine-club shipping concession: when
    `club_subscription_id` is not null it is 2,500 basis points — one quarter — of
    `shipping_tiered_cents`, rounded half up to whole cents; when
    `club_subscription_id` is null it is 0." (PRD 3.5)

    "If the generated order landed in `CLEARED` or in `OVERRIDE_PENDING`,
    `next_run_date` is advanced by the subscription's `cadence`. Advancing a
    `MONTHLY` cadence means the same day-of-month one month later, clamped to that
    month's last day when the day-of-month does not exist — the 31st of January
    advances to the 28th or 29th of February — and advancing a `QUARTERLY` cadence
    means the same day-of-month three months later with the same clamping."
    (PRD 3.8)

    "Finally, when the order names a `club_subscription_id`, that subscription's
    `consumed_shipments` grows by 1 and its `remaining_allotment` is recomputed as
    `annual_allotment` less `consumed_shipments`." (PRD 3.6)

    "An empty candidate set is not an error: the run answers HTTP 200 with
    `generated_count` 0 and an empty `generated_order_ids` array." (PRD 3.8)

    Design: Corner/validations/club_run_date_may_equal_the_clock_but_never_exceed_it
    """
    scape, subscription = _build_due_subscription(api)

    run = scape.club_run("2026-07-31")
    assert run["generated_count"] == 1
    assert run["skipped_count"] == 0
    assert run["skipped_subscription_ids"] == []
    assert len(run["generated_order_ids"]) == 1

    # 6 x 750 ml at 2600 c: 4.500 L on the club discount.
    generated = scape.read_order(run["generated_order_ids"][0])
    assert generated["club_subscription_id"] == subscription["id"]
    a.assert_charge_chain(
        generated,
        total_liters=4.500,
        subtotal_cents=15600,
        shipping_gross_cents=2490,
        shipping_tiered_cents=2490,
        shipping_discount_cents=623,
        shipping_cents=1867,
        excise_tax_cents=211,
        sales_tax_cents=1441,
        pre_fee_total_cents=19119,
        compliance_handling_fee_cents=900,
        total_cents=20019,
    )
    a.assert_order_dimensions(generated, compliance_status="CLEARED")

    advanced = scape.read_subscription(subscription["id"])
    assert advanced["next_run_date"] == "2026-08-15"
    assert advanced["consumed_shipments"] == 1
    assert advanced["remaining_allotment"] == 11

    # A run dated exactly on the clock is accepted, and now finds no candidate.
    on_the_clock = scape.club_run("2026-08-01")
    assert on_the_clock["generated_count"] == 0
    assert on_the_clock["skipped_count"] == 0
    assert on_the_clock["generated_order_ids"] == []
    assert on_the_clock["skipped_subscription_ids"] == []

    assert len(_winery_orders(api, scape.winery_id)) == 1


# ---------------------------------------------------------------------------
# The winery aggregate blocks a consumer who is individually spotless
# ---------------------------------------------------------------------------
MT_SHIP_TO = {"ship_to_state_code": "MT", "ship_to_zip": "59101"}


def _build_mt_aggregate(api):
    """Two consumers fill the winery's 9.000 L MT year; a third is refused."""
    scape = fx.build_landscape(
        api,
        state_rule_overrides={
            "state_code": "MT",
            "per_winery_annual_limit_liters": 9.000,
            "requires_carrier_program": False,
        },
        permit_overrides={"state_code": "MT", "permit_number": "MT-DTC-1"},
        consumer_overrides={"state_code": "MT", "zip_code": "59101"},
    )
    ben = fx.create_verified_consumer(
        api, full_name="Ben Buyer", email="ben@example.com", birthdate="1979-11-30",
        address_line="14 Vine St", state_code="MT", zip_code="59101",
    )
    cleo = fx.create_verified_consumer(
        api, full_name="Cleo Buyer", email="cleo@example.com", birthdate="1990-02-14",
        address_line="16 Vine St", state_code="MT", zip_code="59101",
    )
    first = scape.screen(scape.create_order(**MT_SHIP_TO)["id"])
    second = scape.screen(scape.create_order(consumer_id=ben["id"], **MT_SHIP_TO)["id"])
    third = scape.screen(
        scape.create_order(lines=ONE_BOTTLE, consumer_id=cleo["id"], **MT_SHIP_TO)["id"]
    )
    return {
        "scape": scape,
        "ben": ben,
        "cleo": cleo,
        "first": first,
        "second": second,
        "third": third,
    }


def test_winery_annual_limit_aggregates_across_different_consumers(api):
    """Only the collective total can explain the third consumer's referral.

    "**The winery must have volume headroom.** The winery's calendar-year
    accumulated liters into the destination state plus this order's `total_liters`
    must be at most the state's `per_winery_annual_limit_liters`. Equality clears;
    exceeding fails with `ERR_WINERY_VOLUME_LIMIT_EXCEEDED`. This failure is
    **overridable**." (PRD 3.6)

    "**The consumer must have volume headroom.** The consumer's accumulated rolling
    liters for the destination state, taken from `rolling_liters_by_state`, plus
    this order's `total_liters`, must be at most the state's
    `per_consumer_limit_liters`. Landing exactly on the limit clears; exceeding it
    by any amount at all fails with `ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED`. This
    failure is **overridable**." (PRD 3.6)

    "The **winery's** annual state volume is a separate aggregate with a fixed
    window: for a winery-and-state pair it is the signed sum, rounded half up to
    three decimal places, of all ledger entries for that pair — across every
    consumer, every event type — whose `occurred_at` falls on or after January 1
    at `00:00:00.000Z` of the logical clock's calendar year and on or before the
    logical clock instant." (PRD 3.4)

    "If the highest-ranked failing check *is* one of
    `ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED`, `ERR_WINERY_VOLUME_LIMIT_EXCEEDED` or
    `ERR_ELEVATED_RISK_REVIEW_REQUIRED`, the order moves to `OVERRIDE_PENDING`,
    which is an invitation to the exception workflow rather than a refusal."
    (PRD 3.6)

    Design: Corner/validations/winery_annual_limit_aggregates_across_different_consumers
    """
    built = _build_mt_aggregate(api)
    scape = built["scape"]

    # 4.500 + 4.500 == 9.000 exactly, so the second order still clears.
    a.assert_order_dimensions(built["first"], compliance_status="CLEARED")
    a.assert_order_dimensions(built["second"], compliance_status="CLEARED")

    a.assert_order_dimensions(built["third"], compliance_status="OVERRIDE_PENDING")
    a.assert_rejection(built["third"], "ERR_WINERY_VOLUME_LIMIT_EXCEEDED")

    # The refused buyer has no history of her own, so the consumer gate passed.
    cleo = scape.read_consumer(built["cleo"]["id"])
    assert cleo["rolling_liters_by_state"] == {}

    # The two contributors are individually far under the 27.000 L limit.
    a.assert_liters(
        scape.read_consumer()["rolling_liters_by_state"]["MT"], 4.500, "Ada MT"
    )
    a.assert_liters(
        scape.read_consumer(built["ben"]["id"])["rolling_liters_by_state"]["MT"],
        4.500,
        "Ben MT",
    )


def test_a_parked_order_reserves_no_liters_and_raises_no_exception_by_itself(api):
    """OVERRIDE_PENDING is a referral, not an accrual.

    "A **`DRAFT` → `OVERRIDE_PENDING`** outcome likewise writes the overridable
    identifier into `rejection_error_id` and appends no ledger entry — the liters
    are not reserved while the exception is pending." (PRD 3.6)

    "The exception opens in `status` `OPEN` with `requested_by_user_id` set from the
    raising officer's `X-User-ID`, with `decided_by_user_id`, `decision_note` and
    `decided_at` all null, and the winery's `open_exception_count` — the number of
    `OPEN` exceptions on that winery's orders — grows by 1." (PRD 3.6)

    "The winery's `excise_accrued_cents` grows by the order's `excise_tax_cents` —
    that counter is the running sum of `excise_tax_cents` across every order of the
    winery that has reached `CLEARED` at least once — and `Winery.version`
    increments by 1." (PRD 3.6)

    Design: Corner/validations/winery_annual_limit_aggregates_across_different_consumers
    """
    built = _build_mt_aggregate(api)
    scape = built["scape"]

    rows = _ledger_rows(api, winery_id=scape.winery_id, state_code="MT")
    assert len(rows) == 2
    for row in rows:
        a.assert_ledger_entry(row, event_type="SHIPMENT_ACCEPTED", liters=4.500)
    a.assert_ledger_sums_to(rows, 9.000)

    assert _ledger_rows(api, order_id=built["third"]["id"]) == []

    winery = scape.read_winery()
    # 211 + 211 for the two cleared orders, and nothing for the parked one.
    a.assert_cents(winery["excise_accrued_cents"], 422, "excise_accrued_cents")
    assert winery["open_exception_count"] == 0


# ---------------------------------------------------------------------------
# The carrier requirement is switched by the destination rule
# ---------------------------------------------------------------------------
def _build_two_state_landscape_without_enrollment(api):
    """ACTIVE permits in TX and ID, a GSO program, and no enrollment at all."""
    fx.set_clock(api)
    winery = fx.create_winery(api)
    texas = fx.create_state_rule(api)
    fx.create_state_rule(api, state_code="ID", requires_carrier_program=False)
    permit = fx.create_active_permit(api, winery["id"])
    fx.create_active_permit(
        api, winery["id"], state_code="ID", permit_number="ID-DTC-1"
    )
    program = fx.create_carrier_program(api)
    consumer = fx.create_verified_consumer(api)
    return fx.Landscape(api, winery, texas, permit, program, None, consumer)


def test_carrier_program_enrollment_is_required_only_where_the_state_says_so(api):
    """One winery, one missing enrollment, two different answers.

    "Where a state rule sets `requires_carrier_program`, a winery cannot ship into
    that state on goodwill; it needs a live **carrier enrollment**." (PRD 3.3)

    "When the destination state rule's `requires_carrier_program` is true, the
    winery must hold an enrollment in `APPROVED` whose program's `states_served`
    array contains the order's `ship_to_state_code`; otherwise the outcome is
    `ERR_CARRIER_NOT_ENROLLED`." (PRD 3.3)

    "Two screening rules connect the carrier layer back to the order, and they sit
    adjacent in the evaluation order of §2.9 for a reason — the second only makes
    sense once the first has found an enrollment." (PRD 3.3)

    "A program's `requires_enrollment` flag documents the carrier's own commercial
    demand for enrollment; it is the state rule's `requires_carrier_program` that
    decides whether screening insists on one." (PRD 3.3)

    "An order already sitting at `CLEARED`, `REJECTED` or `OVERRIDE_PENDING` cannot
    be screened again, and the attempt is refused with `ERR_ORDER_ALREADY_SCREENED`
    (HTTP 409)." (PRD 3.6)

    Design: Corner/validations/carrier_program_enrollment_is_required_only_where_the_state_says_so
    """
    scape = _build_two_state_landscape_without_enrollment(api)

    # Flag on, no enrollment.
    refused = scape.screen(scape.create_order(lines=ONE_BOTTLE)["id"])
    a.assert_order_dimensions(refused, compliance_status="REJECTED")
    a.assert_rejection(refused, "ERR_CARRIER_NOT_ENROLLED")

    # Flag off, the same missing enrollment.
    idaho = scape.screen(
        scape.create_order(
            lines=ONE_BOTTLE, ship_to_state_code="ID", ship_to_zip="83702"
        )["id"]
    )
    a.assert_order_dimensions(idaho, compliance_status="CLEARED")
    a.assert_rejection(idaho, None)
    id_rows = _ledger_rows(api, order_id=idaho["id"])
    assert len(id_rows) == 1
    a.assert_ledger_entry(
        id_rows[0], event_type="SHIPMENT_ACCEPTED", liters=0.750, state_code="ID"
    )

    # Flag on, and now an APPROVED enrollment for a program that serves TX.
    fx.create_approved_enrollment(api, scape.winery_id, scape.program_id)
    cleared = scape.screen(scape.create_order(lines=ONE_BOTTLE)["id"])
    a.assert_order_dimensions(cleared, compliance_status="CLEARED")
    a.assert_rejection(cleared, None)

    # The first refusal is terminal on the compliance axis.
    rescreen = api.screen_order(refused["id"], {}, OFFICER_A)
    validate_error(rescreen, "ERR_ORDER_ALREADY_SCREENED", 409)


# ---------------------------------------------------------------------------
# Reroute containment sits behind the scan-legality gate
# ---------------------------------------------------------------------------
def _build_in_transit_shipment_with_ca_rule(api):
    """A TX order picked up, with a CA state rule on file as well."""
    scape = fx.build_landscape(api)
    fx.create_state_rule(api, state_code="CA")
    order = scape.create_cleared_order()
    shipment = scape.label(order["id"])
    scape.pickup(shipment["id"])
    return scape, order, shipment


def test_reroute_containment_is_only_reachable_after_the_state_check(api):
    """The identical cross-state payload answers 409 first and 422 second.

    "A scan type that is not declared from the shipment's current status — a pickup
    on a shipment already `IN_TRANSIT`, a reroute on a shipment that is not in
    `EXCEPTION`, a second reroute on a shipment that has already been rerouted once,
    or any scan at all on a shipment that has reached `DELIVERED` or `RETURNED` — is
    refused with `ERR_SHIPMENT_NOT_ACTIVE` (HTTP 409)." (PRD 3.7)

    "An **`EXCEPTION`** scan moves the shipment `IN_TRANSIT` → `EXCEPTION` and
    requires an `exception_code` of `WEATHER`, `ADDRESS_UNDELIVERABLE`,
    `ADULT_SIGNATURE_UNAVAILABLE` or `REFUSED`, which is recorded on the shipment."
    (PRD 3.7)

    "The supplied `reroute_state_code` must equal the order's existing
    `ship_to_state_code`: a cross-state reroute is refused with
    `ERR_REROUTE_STATE_CHANGE` (HTTP 422) because it would invalidate the permit,
    tax and volume decisions already frozen on the order." (PRD 3.7)

    "A shipment may be rerouted **at most once**, so the scan requires
    `reroute_count` to still be 0." (PRD 3.7)

    Design: Corner/validations/reroute_containment_is_only_reachable_after_the_state_check
    """
    scape, order, shipment = _build_in_transit_shipment_with_ca_rule(api)

    # From IN_TRANSIT a reroute is not declared at all, so the 409 family answers
    # and the containment rule is never reached.
    too_early = api.scan_shipment(
        shipment["id"], f.reroute_scan("90210", "CA"), CARRIER
    )
    validate_error(too_early, "ERR_SHIPMENT_NOT_ACTIVE", 409)

    excepted = scape.scan(shipment["id"], f.exception_scan("ADDRESS_UNDELIVERABLE"))
    assert excepted["status"] == "EXCEPTION"
    assert excepted["exception_code"] == "ADDRESS_UNDELIVERABLE"

    # The same payload now reaches the containment rule.
    cross_state = api.scan_shipment(
        shipment["id"], f.reroute_scan("90210", "CA"), CARRIER
    )
    validate_error(cross_state, "ERR_REROUTE_STATE_CHANGE", 422)

    unchanged = scape.read_shipment(shipment["id"])
    assert unchanged["status"] == "EXCEPTION"
    assert unchanged["reroute_count"] == 0
    assert unchanged["reroute_zip"] is None


def test_a_same_state_reroute_rewrites_only_the_destination_zip(api):
    """The accepted reroute closes the exception cycle and moves no money.

    "A **`REROUTE_ACCEPTED`** scan moves the shipment `EXCEPTION` → `IN_TRANSIT`,
    closing the `IN_TRANSIT` → `EXCEPTION` → `IN_TRANSIT` cycle, and carries a
    `reroute_zip` and a `reroute_state_code`." (PRD 3.7)

    "On success the shipment's `status` becomes `IN_TRANSIT`, `reroute_zip` is
    recorded, `reroute_count` grows by 1, and `exception_code` is cleared to null;
    on the order, `ship_to_zip` is rewritten to the accepted reroute ZIP and
    `Order.version` increments by 1." (PRD 3.7)

    "There is no ledger movement of any kind — the destination state has not
    changed, so neither tax nor volume attribution changes." (PRD 3.7)

    "Every monetary and volumetric field on the order and on each of its lines is
    computed exactly once, at creation, from the governing state rule and the
    winery, and then **frozen**." (PRD 3.5)

    Design: Corner/validations/reroute_containment_is_only_reachable_after_the_state_check
    """
    scape, order, shipment = _build_in_transit_shipment_with_ca_rule(api)
    scape.scan(shipment["id"], f.exception_scan("ADDRESS_UNDELIVERABLE"))

    rerouted = scape.scan(shipment["id"], f.reroute_scan("78702", "TX"))
    assert rerouted["status"] == "IN_TRANSIT"
    assert rerouted["reroute_zip"] == "78702"
    assert rerouted["reroute_count"] == 1
    assert rerouted["exception_code"] is None

    moved = scape.read_order(order["id"])
    assert moved["ship_to_zip"] == "78702"
    assert moved["ship_to_state_code"] == "TX"
    a.assert_cents(moved["excise_tax_cents"], 211, "excise_tax_cents")
    a.assert_cents(moved["sales_tax_cents"], 2284, "sales_tax_cents")

    rows = _ledger_rows(api, order_id=order["id"])
    assert len(rows) == 1
    a.assert_ledger_entry(
        rows[0], event_type="SHIPMENT_ACCEPTED", liters=4.500, state_code="TX"
    )
