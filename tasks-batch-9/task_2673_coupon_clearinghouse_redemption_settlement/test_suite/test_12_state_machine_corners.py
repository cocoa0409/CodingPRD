"""Guards on individual transitions, and the states that admit nothing further.

Each transition carries preconditions beyond its from-state, terminal states
refuse every trigger, and a refused trigger must leave no trace of itself.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN,
    ANALYST,
    ANALYST_2,
    CLERK,
    FRAUD_ANALYST_ID,
    OFFICER,
    CANONICAL_DATABAR_PAYLOAD,
    COUNTERFEIT_DATABAR_PAYLOAD,
    DisputeStatus,
    FeeTier,
    IntakeStatus,
    InvoiceStatus,
    ItemStatus,
    LotRejectReason,
    LotStatus,
    ManufacturerStatus,
    OfferStatus,
    RejectCode,
    RetailerStatus,
    SettlementStatus,
    StatementStatus,
    ValuationVariant,
    api_errors as err,
    assert_fields,
    assert_manufacturer_ledger,
    assert_millis_timestamp,
    assert_money,
    assert_nulls,
    assert_rate_equals,
    assert_retailer_unpaid,
    assert_sweep_counters,
    factories as f,
    make_manufacturer_headers,
)


def _contract_market(build, **overrides):
    """The contract-rate issuer and a STANDARD, NET_30 retailer, one unit per coupon."""
    terms = dict(
        gs1_company_prefix="038000",
        handling_fee_policy="CONTRACT_RATE",
        dispute_window_days=45,
        channel_capability="BOTH",
        payment_terms="NET_30",
        base_fee_tier="STANDARD",
        fraud_scoring_mode="ROLLING_WINDOW",
        offer_code="SOUP50",
        face_value_cents=50,
        handling_fee_cents=7,
        expiration_date="2026-12-31",
        redemption_instructions="Save 50c on one can",
        max_redemptions=100000,
        purchase_requirement_units=1,
    )
    terms.update(overrides)
    return build.market(**terms)


def test_01_a_registered_offer_whose_expiry_has_passed_cannot_be_activated(
        api, build):
    """The from-state is right and the date is wrong, so the date decides.

    "From `REGISTERED`, and only when the offer's `expiration_date` is on or after
    the logical clock's calendar date, the offer advances `REGISTERED` → `ACTIVE`,
    which opens it both to lot creation and to digital clipping."

    "An offer whose expiry has already passed cannot be activated at all and is
    refused with `ERR_OFFER_EXPIRED`."

    "Every `Offer` whose status is `ACTIVE` and whose `expiration_date` is
    strictly earlier than the new clock's calendar date moves from `ACTIVE` to
    `EXPIRED`, processed in `created_at` ascending order."

    Design: Corner/state_machines/offer_activation_refused_once_expiration_date_has_passed
    """
    mfr = build.manufacturer(gs1_company_prefix="038000",
                             legal_name="Kellwood Foods")
    offer = build.offer(mfr["id"], offer_code="SOUP50",
                        expiration_date="2026-08-10")
    build.register(offer)

    sweep = validate_success(api.set_clock("2026-08-11T00:00:00Z"))
    assert_sweep_counters(sweep, "2026-08-11T00:00:00Z", expired_offer_count=0,
                          expired_clip_count=0, withdrawn_dispute_count=0)

    refused = api.activate_offer(offer["id"], ADMIN)
    validate_error(refused, err.ERR_OFFER_EXPIRED, expected_status=422)

    unchanged = validate_success(api.get_offer(offer["id"], ADMIN))
    assert_fields(unchanged, {"status": OfferStatus.REGISTERED, "version": 2})


def test_02_a_lot_cannot_be_valued_until_its_last_image_lands(api, build):
    """Two of three images is a 422, and the identical call passes at three.

    "The lot must be in `SORTED`; its `captured_item_count` must equal its
    `sample_size`, or the request is refused with `ERR_SAMPLE_INCOMPLETE` because a
    lot cannot be valued until the full sample has been imaged; and the retailer
    that owns the lot's submission must not be `SUSPENDED`."

    "When the `counted_qty` is at most 40, the whole bucket is imaged:
    `sample_size` equals `counted_qty` and `valuation_variant` is `FULL_COUNT`."

    Design: Corner/state_machines/lot_finalize_refused_until_full_sample_captured
    """
    market = _contract_market(build)
    build.purchase_record(market["retailer_id"], market["offer_id"], "POS-1",
                          "2026-07-05", 1)
    submission = build.verified_submission(market["retailer_id"], 3,
                                           "2026-07-01", "2026-07-31")
    lot = build.lot(submission["id"], market["offer_id"],
                    market["manufacturer_id"], 3)
    build.capture(lot["id"], [
        f.item_payload(market["barcode"], f"s3://img/{index}.jpg", "2026-07-06",
                       pos_transaction_ref="POS-1")
        for index in (1, 2)
    ])

    validate_error(api.finalize_lot(lot["id"], ANALYST),
                   err.ERR_SAMPLE_INCOMPLETE, expected_status=422)

    still_open = validate_success(api.get_lot(lot["id"], CLERK))
    assert_fields(still_open, {"status": LotStatus.SORTED, "sample_size": 3,
                              "captured_item_count": 2})
    captured, _meta = validate_paginated(api.list_items(CLERK, lot_id=lot["id"]))
    assert [row["status"] for row in captured] == [ItemStatus.CAPTURED] * 2, (
        "the refused finalization adjudicated nothing"
    )

    build.capture(lot["id"], [
        f.item_payload(market["barcode"], "s3://img/3.jpg", "2026-07-06",
                       pos_transaction_ref="POS-1")])

    validated = validate_success(api.finalize_lot(lot["id"], ANALYST))
    assert_fields(validated, {
        "status": LotStatus.VALIDATED,
        "captured_item_count": 3,
        "accepted_qty": 3,
        "rejected_qty": 0,
        "projected_accepted_units": 3,
        "valuation_variant": ValuationVariant.FULL_COUNT,
        "adjudicated_by_user_id": FRAUD_ANALYST_ID,
    })
    assert_money(validated, "gross_face_value_cents", 150)
    assert_money(validated, "handling_fee_cents", 21)

    closed = validate_success(api.get_submission(submission["id"], ANALYST))
    assert_fields(closed, {"intake_status": IntakeStatus.CLOSED,
                           "settlement_status": SettlementStatus.PENDING,
                           "rejected_lot_count": 0})
    assert_money(closed, "settled_gross_face_value_cents", 150)
    assert_money(closed, "settled_handling_fee_cents", 21)
    assert_money(closed, "adjudicated_face_value_cents", 150)


def test_03_a_withdrawn_offer_refuses_both_a_second_withdrawal_and_a_register(
        api, build):
    """The one terminal state of the offer machine keeps its first reason.

    "The manufacturer that owns the offer (its `manufacturer_id` matching the
    acting `X-User-ID`) may withdraw it from `REGISTERED`, `ACTIVE` or `EXPIRED`,
    supplying a `withdrawn_reason` of 1 to 200 characters that is stored on the
    offer; the offer becomes `WITHDRAWN`, which is terminal."

    "Registration advances the offer `DRAFT` → `REGISTERED` and, in the same
    call, mints `barcode_payload` once and for all; it is never recomputed
    afterwards."

    Design: Corner/state_machines/offer_withdraw_from_withdrawn_is_locked
    """
    mfr = build.manufacturer(gs1_company_prefix="038000",
                             legal_name="Kellwood Foods")
    headers = make_manufacturer_headers(mfr["id"])
    offer = build.offer(mfr["id"], offer_code="SOUP50")
    build.register(offer)

    withdrawn = validate_success(
        api.withdraw_offer(offer["id"], "Artwork recalled", headers))
    assert_fields(withdrawn, {"status": OfferStatus.WITHDRAWN,
                              "withdrawn_reason": "Artwork recalled"})

    validate_error(api.withdraw_offer(offer["id"], "Second attempt", headers),
                   err.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    validate_error(api.register_offer(offer["id"], headers),
                   err.ERR_INVALID_STATE_TRANSITION, expected_status=409)

    final = validate_success(api.get_offer(offer["id"], headers))
    assert_fields(final, {"status": OfferStatus.WITHDRAWN,
                          "withdrawn_reason": "Artwork recalled",
                          "barcode_payload": CANONICAL_DATABAR_PAYLOAD,
                          "version": 3})


@pytest.fixture
def draft_statement(build):
    """One cleared coupon settled into a DRAFT statement of 57 cents.

    Gross 50 and handling fee 7 against a STANDARD, NET_30 retailer, with the
    statement left unscheduled so both the billing and scheduling corners can
    start from it.
    """
    market = _contract_market(build)
    build.purchase_record(market["retailer_id"], market["offer_id"], "POS-1",
                          "2026-07-05", 1)
    submission = build.verified_submission(market["retailer_id"], 1,
                                           "2026-07-01", "2026-07-31")
    lot = build.lot(submission["id"], market["offer_id"],
                    market["manufacturer_id"], 1)
    build.capture(lot["id"], [
        f.item_payload(market["barcode"], "s3://img/1.jpg", "2026-07-05",
                       pos_transaction_ref="POS-1")])
    build.finalize(lot["id"])
    statement = build.issue_statement(submission["id"])
    return {"market": market, "manufacturer_id": market["manufacturer_id"],
            "retailer_id": market["retailer_id"],
            "submission_id": submission["id"], "statement": statement,
            "statement_id": statement["id"]}


def test_04_a_freshly_billed_invoice_owes_its_whole_total(api, draft_statement):
    """The shortfall starts at the billed total, not at zero.

    "`billed_face_value_cents` is the sum of `gross_face_value_cents` over the
    named statements; `billed_handling_fee_cents` is the sum of their
    `handling_fee_total_cents`."

    "`funded_amount_cents` starts at 0 and `funding_shortfall_cents` starts equal
    to `billed_total_cents`, which is the general identity: the shortfall is
    always the billed total minus the funded amount, floored at zero."

    "The invoice is created in status `ISSUED`, and each named statement has its
    `manufacturer_invoice_id` set to the new invoice."

    Design: Corner/state_machines/manufacturer_invoice_initial_state_is_issued_with_full_shortfall
    """
    statement_id = draft_statement["statement_id"]
    manufacturer_id = draft_statement["manufacturer_id"]

    invoice = validate_success(api.create_invoice(f.invoice_payload(
        manufacturer_id, "2026-07-01", "2026-07-31", [statement_id]),
        OFFICER), 201)

    assert_fields(invoice, {"status": InvoiceStatus.ISSUED, "version": 1,
                            "manufacturer_id": manufacturer_id})
    assert_money(invoice, "billed_face_value_cents", 50)
    assert_money(invoice, "billed_handling_fee_cents", 7)
    assert_money(invoice, "billed_clearing_fee_cents", 1)
    assert_money(invoice, "billed_total_cents", 58)
    assert_money(invoice, "funded_amount_cents", 0)
    assert_money(invoice, "funding_shortfall_cents", 58)

    statement = validate_success(api.get_statement(statement_id, OFFICER))
    assert_fields(statement, {"manufacturer_invoice_id": invoice["id"],
                              "status": StatementStatus.DRAFT})
    assert_nulls(statement, ["scheduled_pay_date"])

    issuer = validate_success(api.get_manufacturer(manufacturer_id, OFFICER))
    assert_fields(issuer, {"status": ManufacturerStatus.ACTIVE})
    assert_manufacturer_ledger(issuer, funded_total=0, disbursed_total=0)
    assert_money(issuer, "funding_balance_cents", 0)


def test_05_a_replayed_schedule_credits_the_retailer_ledger_only_once(
        api, draft_statement):
    """The second schedule is a 409 that neither re-credits nor re-dates.

    "The term is 15 days for `NET_15`, 30 days for `NET_30` and 45 days for
    `NET_45`."

    "Scheduling then moves the statement `DRAFT` → `SCHEDULED`, moves the
    submission's `settlement_status` `PENDING` → `STATEMENT_ISSUED`, and increases
    the retailer's `unpaid_balance_cents` by the statement's `net_payable_cents`,
    bumping the retailer's `version`."

    Design: Corner/state_machines/statement_schedule_twice_leaves_unpaid_balance_credited_once
    """
    statement_id = draft_statement["statement_id"]

    scheduled = validate_success(api.schedule_statement(statement_id, OFFICER))
    assert_fields(scheduled, {"status": StatementStatus.SCHEDULED,
                              "scheduled_pay_date": "2026-08-31"})

    validate_error(api.schedule_statement(statement_id, OFFICER),
                   err.ERR_INVALID_STATE_TRANSITION, expected_status=409)

    reread = validate_success(api.get_statement(statement_id, OFFICER))
    assert_fields(reread, {"status": StatementStatus.SCHEDULED,
                           "scheduled_pay_date": "2026-08-31",
                           "version": 2})
    assert_money(reread, "net_payable_cents", 57)

    retailer = validate_success(
        api.get_retailer(draft_statement["retailer_id"], OFFICER))
    assert_retailer_unpaid(retailer, 57)

    submission = validate_success(
        api.get_submission(draft_statement["submission_id"], OFFICER))
    assert_fields(submission,
                  {"settlement_status": SettlementStatus.STATEMENT_ISSUED})
    assert_nulls(submission, ["hold_reason"])


def test_06_only_reinstatement_gives_the_contracted_tier_back(api, build):
    """A rescore takes the tier, an admin suspension keeps it, reinstatement returns it.

    "Administrative suspension takes a `reason` and applies from `ACTIVE` or
    `WATCHLIST`, driving the retailer to `SUSPENDED` and forcing its effective
    `handling_fee_tier` to `PROBATION`; it deliberately does not touch
    `fraud_score`, so the next rescore can re-derive the gate from evidence rather
    than from the administrator's judgement."

    "Reinstatement, also taking a `reason`, is available only from `SUSPENDED`:
    the retailer returns to `ACTIVE` and its `handling_fee_tier` is restored to
    `base_fee_tier`, again leaving `fraud_score` untouched — which means the very
    next rescore may push it straight back to `WATCHLIST` or `SUSPENDED`."

    "At `70.00` or above but below `90.00` it is `WATCHLIST`."

    "Because `PROBATION` drops the handling-fee multiplier to 0.80, a watchlisted
    retailer immediately earns less on every lot finalized from that moment on —
    the tier is read at finalization time, not at intake time."

    Design: Corner/state_machines/retailer_watchlist_then_admin_suspend_reinstate_restores_base_tier
    """
    market = _contract_market(build, base_fee_tier="PREFERRED")
    retailer_id = market["retailer_id"]
    build.purchase_record(retailer_id, market["offer_id"], "POS-1",
                          "2026-07-05", 1)
    submission = build.verified_submission(retailer_id, 5, "2026-07-01",
                                           "2026-07-31")
    lot = build.lot(submission["id"], market["offer_id"],
                    market["manufacturer_id"], 5)
    build.capture(lot["id"], [
        f.item_payload(market["barcode"], "s3://img/1.jpg", "2026-07-05",
                       pos_transaction_ref="POS-1"),
        f.item_payload(market["barcode"], "s3://img/2.jpg", "2026-07-05",
                       pos_transaction_ref="POS-1"),
        f.item_payload(COUNTERFEIT_DATABAR_PAYLOAD, "s3://img/3.jpg",
                       "2026-07-05", pos_transaction_ref="POS-1"),
        f.item_payload(market["barcode"], "s3://img/4.jpg", "2026-07-05",
                       pos_transaction_ref="POS-9"),
        f.item_payload(market["barcode"], "s3://img/5.jpg", "2026-07-05",
                       pos_transaction_ref="POS-9"),
    ])
    validated = build.finalize(lot["id"])
    assert_fields(validated, {"status": LotStatus.VALIDATED, "accepted_qty": 2,
                              "rejected_qty": 3})
    assert_money(validated, "gross_face_value_cents", 100)
    assert_money(validated, "handling_fee_cents", 16)

    watchlisted = build.rescore(retailer_id)
    assert_rate_equals(watchlisted["duplicate_rate"], "0.00", "duplicate_rate")
    assert_rate_equals(watchlisted["misredemption_rate"], "40.00",
                       "misredemption_rate")
    assert_rate_equals(watchlisted["counterfeit_rate"], "20.00",
                       "counterfeit_rate")
    assert_rate_equals(watchlisted["fraud_score"], "80.00", "fraud_score")
    assert_fields(watchlisted, {"status": RetailerStatus.WATCHLIST,
                                "handling_fee_tier": FeeTier.PROBATION})

    suspended = validate_success(api.suspend_retailer(
        retailer_id, f.suspend_payload("Manual hold pending site audit"), ADMIN))
    assert_fields(suspended, {"status": RetailerStatus.SUSPENDED,
                              "handling_fee_tier": FeeTier.PROBATION})
    assert_rate_equals(suspended["fraud_score"], "80.00", "fraud_score")

    reinstated = validate_success(api.reinstate_retailer(
        retailer_id, f.reinstate_payload("Site audit cleared"), ADMIN))
    assert_fields(reinstated, {"status": RetailerStatus.ACTIVE,
                               "handling_fee_tier": FeeTier.PREFERRED,
                               "base_fee_tier": FeeTier.PREFERRED,
                               "version": 4})
    assert_rate_equals(reinstated["fraud_score"], "80.00", "fraud_score")

    settled_lot = validate_success(api.get_lot(lot["id"], ANALYST))
    assert_money(settled_lot, "handling_fee_cents", 16)


def test_07_both_legs_of_the_information_loop_are_from_state_guarded(api, build):
    """A repeated request and a repeated resubmit are state errors, not cap errors.

    "An analyst may bounce the appeal back for more evidence, supplying an
    `info_request_note`; that moves the dispute `UNDER_REVIEW` → `INFO_REQUESTED`
    and increments `info_request_count` by 1."

    "The retailer answers by resubmitting with a fresh `narrative`, which is
    appended to the existing `narrative` and returns the dispute `INFO_REQUESTED`
    → `UNDER_REVIEW`; only the retailer named on the dispute may resubmit."

    "That closes one turn of an `UNDER_REVIEW` → `INFO_REQUESTED` →
    `UNDER_REVIEW` cycle, and the cycle is capped at two information requests per
    dispute: a third attempt, when `info_request_count` has already reached 2, is
    refused with `ERR_INFO_ROUND_LIMIT`, which terminates the negotiation and
    forces the analyst to decide on what is in front of them."

    Design: Corner/state_machines/dispute_request_info_twice_in_a_row_is_an_invalid_transition
    """
    market = _contract_market(build)
    retailer_id = market["retailer_id"]
    build.purchase_record(retailer_id, market["offer_id"], "POS-1",
                          "2026-07-05", 1)
    submission = build.verified_submission(retailer_id, 3, "2026-07-01",
                                           "2026-07-31")
    lot_a = build.lot(submission["id"], market["offer_id"],
                      market["manufacturer_id"], 2)
    lot_b = build.lot(submission["id"], market["offer_id"],
                      market["manufacturer_id"], 1)
    build.capture(lot_a["id"], [
        f.item_payload(market["barcode"], f"s3://img/a{index}.jpg",
                       "2026-07-05", pos_transaction_ref="POS-1")
        for index in (1, 2)
    ])
    build.capture(lot_b["id"], [
        f.item_payload(market["barcode"], "s3://img/b1.jpg", "2026-07-05",
                       pos_transaction_ref="POS-9")])
    build.finalize(lot_a["id"])
    rejected = build.finalize(lot_b["id"])
    assert_fields(rejected, {"status": LotStatus.LOT_REJECTED,
                             "reject_reason": LotRejectReason.ALL_ITEMS_REJECTED})
    assert_money(rejected, "gross_face_value_cents", 0)
    assert_money(rejected, "handling_fee_cents", 0)

    dispute = build.file_dispute(lot_b["id"], retailer_id,
                                 reason_code="POS_DATA_LATE",
                                 narrative="Register data was uploaded late.")
    assert_fields(dispute, {"status": DisputeStatus.UNDER_REVIEW,
                            "retailer_id": retailer_id,
                            "info_request_count": 0})
    assert_money(dispute, "claimed_face_value_cents", 50)
    assert_fields(validate_success(api.get_lot(lot_b["id"], ANALYST)),
                  {"status": LotStatus.DISPUTED})

    dispute_id = dispute["id"]
    asked = validate_success(api.request_dispute_info(
        dispute_id, "Send the POS extract", ANALYST_2))
    assert_fields(asked, {"status": DisputeStatus.INFO_REQUESTED,
                          "info_request_count": 1})

    validate_error(api.request_dispute_info(dispute_id, "Send it again",
                                           ANALYST_2),
                   err.ERR_INVALID_STATE_TRANSITION, expected_status=409)

    answered = validate_success(api.resubmit_dispute(
        dispute_id, "Extract attached", market["ret_headers"]))
    assert_fields(answered, {"status": DisputeStatus.UNDER_REVIEW,
                             "info_request_count": 1})

    validate_error(api.resubmit_dispute(dispute_id, "Extract attached twice",
                                        market["ret_headers"]),
                   err.ERR_INVALID_STATE_TRANSITION, expected_status=409)

    final = validate_success(api.get_dispute(dispute_id, ANALYST_2))
    assert_fields(final, {"status": DisputeStatus.UNDER_REVIEW,
                          "info_request_count": 1, "version": 3})


@pytest.fixture
def ladder_lot(api, build):
    """Six coupons arranged so one finalize produces every adjudication outcome.

    The offer expires 2026-08-01 and the clock then moves to 2026-08-05, which
    leaves the offer EXPIRED but still well inside its thirty-day grace, so the
    lot is legal and the expiry test has something to bite on.
    """
    market = _contract_market(build, expiration_date="2026-08-01")
    sweep = validate_success(api.set_clock("2026-08-05T00:00:00Z"))
    assert_sweep_counters(sweep, "2026-08-05T00:00:00Z", expired_offer_count=1,
                          expired_clip_count=0, withdrawn_dispute_count=0)

    record_one = build.purchase_record(market["retailer_id"], market["offer_id"],
                                       "POS-1", "2026-08-01", 1)
    record_two = build.purchase_record(market["retailer_id"], market["offer_id"],
                                       "POS-2", "2026-08-01", 1)
    submission = build.verified_submission(market["retailer_id"], 6,
                                           "2026-07-01", "2026-07-31")
    lot = build.lot(submission["id"], market["offer_id"],
                    market["manufacturer_id"], 6)
    build.capture(lot["id"], [
        f.item_payload(market["barcode"], "s3://img/1.jpg", "2026-08-01",
                       serial_number="S1", pos_transaction_ref="POS-1"),
        f.item_payload(COUNTERFEIT_DATABAR_PAYLOAD, "s3://img/2.jpg",
                       "2026-08-02", pos_transaction_ref="POS-1"),
        f.item_payload(market["barcode"], "s3://img/3.jpg", "2026-08-02",
                       pos_transaction_ref="POS-1"),
        f.item_payload(market["barcode"], "s3://img/4.jpg", "2026-08-01",
                       serial_number="S1"),
        f.item_payload(market["barcode"], "s3://img/5.jpg", "2026-08-01",
                       pos_transaction_ref="POS-9"),
        f.item_payload(market["barcode"], "s3://img/6.jpg", "2026-08-01",
                       pos_transaction_ref="POS-2", claimed_units=2),
    ])
    validated = build.finalize(lot["id"])
    rows, _meta = validate_paginated(
        api.list_items(ANALYST, lot_id=lot["id"], limit=10))
    return {
        "market": market,
        "retailer_id": market["retailer_id"],
        "submission_id": submission["id"],
        "lot": validated,
        "record_one_id": record_one["id"],
        "record_two_id": record_two["id"],
        "by_image": {row["image_uri"]: row for row in rows},
    }


def test_08_one_finalize_produces_all_five_outcomes_in_ladder_order(ladder_lot):
    """The counterfeit outranks its own expiry and the duplicate outranks the missing ref.

    "The ladder has four tests, evaluated in a fixed order, and the first one that
    fires decides the outcome; if none fires the coupon clears."

    "This step outranks every later one, so a coupon that is both counterfeit and
    expired lands in `REJECTED_COUNTERFEIT`, not in `REJECTED_EXPIRED`."

    "Step three outranks step four: a coupon that is both a duplicate serial and
    unbacked by purchase data lands in `REJECTED_DUPLICATE`, not in
    `REJECTED_MISREDEEMED`."

    Design: Corner/state_machines/coupon_item_adjudication_ladder_produces_all_five_branches
    """
    by_image = ladder_lot["by_image"]
    assert len(by_image) == 6, "all six coupons must be readable by their image"

    cleared = by_image["s3://img/1.jpg"]
    assert_fields(cleared, {
        "status": ItemStatus.ACCEPTED,
        "matched_purchase_record_id": ladder_lot["record_one_id"]})
    assert_nulls(cleared, ["reject_code", "duplicate_of_item_id"])

    counterfeit = by_image["s3://img/2.jpg"]
    assert_fields(counterfeit, {"status": ItemStatus.REJECTED_COUNTERFEIT,
                                "reject_code": RejectCode.BARCODE_MISMATCH})
    assert_nulls(counterfeit, ["matched_purchase_record_id"])

    expired = by_image["s3://img/3.jpg"]
    assert_fields(expired, {"status": ItemStatus.REJECTED_EXPIRED,
                            "reject_code": RejectCode.EXPIRED_AT_POS})

    duplicate = by_image["s3://img/4.jpg"]
    assert_fields(duplicate, {"status": ItemStatus.REJECTED_DUPLICATE,
                              "reject_code": RejectCode.DUPLICATE_SERIAL,
                              "duplicate_of_item_id": cleared["id"]})

    unbacked = by_image["s3://img/5.jpg"]
    assert_fields(unbacked, {"status": ItemStatus.REJECTED_MISREDEEMED,
                             "reject_code": RejectCode.NO_PURCHASE_MATCH})
    assert_nulls(unbacked, ["matched_purchase_record_id"])

    short_basket = by_image["s3://img/6.jpg"]
    assert_fields(short_basket, {
        "status": ItemStatus.REJECTED_MISREDEEMED,
        "reject_code": RejectCode.INSUFFICIENT_QUALIFYING_UNITS,
        "matched_purchase_record_id": ladder_lot["record_two_id"]})

    for row in by_image.values():
        assert row["status"] != ItemStatus.CAPTURED, (
            "the bulk pass leaves no coupon unadjudicated"
        )
        assert_millis_timestamp(row["adjudicated_at"], "adjudicated_at")


def test_09_the_six_outcomes_weight_to_one_hundredth_over_the_suspend_line(
        api, build, ladder_lot):
    """16.67, 33.33 and 16.67 weight to 90.008, which rounds to 90.01.

    "Three component rates come out of that pool, each computed as the count of
    matching items multiplied by one hundred, divided by the pool size, rounded
    half up to two decimal places: `duplicate_rate` counts items in
    `REJECTED_DUPLICATE`, `misredemption_rate` counts items in
    `REJECTED_MISREDEEMED`, and `counterfeit_rate` counts items in
    `REJECTED_COUNTERFEIT`."

    "The `duplicate_rate` is multiplied by 1.40, the `misredemption_rate` by 1.00
    and the `counterfeit_rate` by 2.00; the three products are added; the total is
    rounded half up to two decimal places; and the result is clamped so that it
    can never exceed `100.00`."

    "At `90.00` or above the retailer's target status is `SUSPENDED`."

    Design: Corner/state_machines/coupon_item_adjudication_ladder_produces_all_five_branches
    """
    assert_fields(ladder_lot["lot"], {"status": LotStatus.VALIDATED,
                                      "accepted_qty": 1, "rejected_qty": 6})
    assert_money(ladder_lot["lot"], "gross_face_value_cents", 50)
    assert_money(ladder_lot["lot"], "handling_fee_cents", 7)

    submission = validate_success(
        api.get_submission(ladder_lot["submission_id"], ANALYST))
    assert_fields(submission, {"intake_status": IntakeStatus.CLOSED,
                               "settlement_status": SettlementStatus.PENDING,
                               "rejected_lot_count": 0})
    assert_money(submission, "declared_face_value_cents", 300)
    assert_money(submission, "accepted_item_face_value_cents", 50)
    assert_money(submission, "rejected_item_face_value_cents", 300)
    assert_money(submission, "adjudicated_face_value_cents", 350)

    before = validate_success(api.get_retailer(ladder_lot["retailer_id"], ANALYST))
    assert_fields(before, {"status": RetailerStatus.ACTIVE})
    assert_rate_equals(before["fraud_score"], "0.00", "fraud_score")

    rescored = build.rescore(ladder_lot["retailer_id"])
    assert_rate_equals(rescored["duplicate_rate"], "16.67", "duplicate_rate")
    assert_rate_equals(rescored["misredemption_rate"], "33.33",
                       "misredemption_rate")
    assert_rate_equals(rescored["counterfeit_rate"], "16.67", "counterfeit_rate")
    assert_rate_equals(rescored["fraud_score"], "90.01", "fraud_score")
    assert_fields(rescored, {"status": RetailerStatus.SUSPENDED,
                             "handling_fee_tier": FeeTier.PROBATION})
