"""Warranty cover, claim resolution, the unauthorised-move cascade and the ledger."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_climate_reading,
    assert_client_money_conservation,
    assert_warranty,
    assert_warranty_claim,
    file_warranty_claim,
    make_client_headers,
    make_shop_manager_headers,
    read_client,
    read_instrument,
    read_ledger,
    read_warranty,
    set_clock,
    setup_completed_tune_order,
    setup_submitted_warranty_claim,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_claim_payload,
)

MANAGER = TEST_USERS["shop_manager_headers"]
COORDINATOR = TEST_USERS["move_coordinator_headers"]


def test_claim_past_half_the_term_resolves_as_a_prorated_credit(api):
    """PRD 3.9: "`elapsed_fraction` is the whole days elapsed from the warranty's
    `start_date` to the clock's date, divided by `term_days`, clamped into the range 0.0
    through 1.0, and rounded half up to **four** decimal places — and the rounding
    happens *before* the comparison and before the credit is multiplied, not after."
    PRD 3.9: "When it is 0.50 or above, the `resolution_variant` is `PRORATED_CREDIT`
    and `credit_cents` is `covered_price_cents` multiplied by one minus
    `elapsed_fraction`, rounded half up to whole cents; a provisional `WARRANTY_CREDIT`
    ledger row for that positive amount is appended immediately, at submission, before
    anyone has looked at the claim."
    PRD 3.9: "The `term_days` follows the service performed: 90 days for a `TUNE`, 45
    for a `PITCH_RAISE`, 365 for a `REGULATE`, 180 for a `VOICE`, and 1095 for a
    `REBUILD`."

    Design: Difficulty/dual_variant_calc/warranty_claim_prorated_credit_vs_free_reservice
    """
    ctx = setup_completed_tune_order(funding=100000)
    warranty = ctx["warranty"]
    assert_warranty(warranty)
    assert warranty["covered_price_cents"] == 19500
    assert warranty["term_days"] == 90

    set_clock("2026-06-20T00:00:00Z")
    current = read_warranty(warranty["id"])
    claim = file_warranty_claim(
        current["id"], ctx["client"]["id"], current["version"],
        reported_issue="unison drift in the tenor break",
    )

    assert_warranty_claim(claim)
    assert claim["elapsed_fraction"] == 0.5556, "50 of 90 days, to four decimal places"
    assert claim["resolution_variant"] == "PRORATED_CREDIT"
    assert claim["credit_cents"] == 8666

    assert read_warranty(warranty["id"])["claim_count"] == 1
    credits = [
        row for row in read_ledger(ctx["client"]["id"])
        if row["entry_type"] == "WARRANTY_CREDIT"
    ]
    assert [row["amount_cents"] for row in credits] == [8666]
    assert read_client(ctx["client"]["id"])["account_credit_cents"] == 89166


def test_claim_before_half_the_term_resolves_as_a_free_reservice(api):
    """PRD 3.9: "When `elapsed_fraction` is **strictly below** 0.50, the
    `resolution_variant` is `FREE_RESERVICE`, `credit_cents` is 0, and no ledger row is
    appended at all — the client is entitled to have the work redone rather than to
    money."
    PRD 3.9: "`elapsed_fraction` is the whole days elapsed from the warranty's
    `start_date` to the clock's date, divided by `term_days`, clamped into the range 0.0
    through 1.0, and rounded half up to **four** decimal places — and the rounding
    happens *before* the comparison and before the credit is multiplied, not after."

    Design: Difficulty/dual_variant_calc/warranty_claim_prorated_credit_vs_free_reservice
    """
    ctx = setup_completed_tune_order(funding=100000)

    set_clock("2026-06-14T00:00:00Z")
    current = read_warranty(ctx["warranty"]["id"])
    claim = file_warranty_claim(
        current["id"], ctx["client"]["id"], current["version"],
        reported_issue="unison drift in the tenor break",
    )

    assert claim["elapsed_fraction"] == 0.4889, "44 of 90 days, short of the half"
    assert claim["resolution_variant"] == "FREE_RESERVICE"
    assert claim["credit_cents"] == 0

    credits = [
        row for row in read_ledger(ctx["client"]["id"])
        if row["entry_type"] == "WARRANTY_CREDIT"
    ]
    assert credits == [], "no ledger row is appended at all"
    assert read_client(ctx["client"]["id"])["account_credit_cents"] == 80500


def test_unauthorized_move_voids_the_warranty_and_denies_its_claim(api):
    """PRD 2.11: "Hop 1: the instrument's `custody_status` becomes `IN_TRANSIT` and
    `unauthorized_move_flag` becomes true. Hop 2: *because* the flag was raised, every
    warranty on that instrument whose status is `ACTIVE` or `TRANSFERRED` moves to
    `VOIDED` with `void_reason` `UNAUTHORIZED_MOVE`, processed in warranty `created_at`
    ascending order. Hop 3: *because* a warranty was voided, every claim of that
    warranty whose status is `SUBMITTED` or `UNDER_REVIEW` moves to `DENIED`, processed
    in claim `created_at` ascending order."
    PRD 3.2: "when it is **omitted**, `unauthorized_move_flag` is set to true and
    Cascade A fires, voiding the instrument's warranties as described in §2.11."

    Design: Difficulty/transitive_cascade/cascade_a_unauthorized_move_depth_five
    """
    ctx = setup_submitted_warranty_claim()

    validate_success(
        api.create_custody_transition(
            ctx["instrument"]["id"], {"to_custody_status": "IN_TRANSIT"}, COORDINATOR
        )
    )

    instrument = read_instrument(ctx["instrument"]["id"])
    assert instrument["custody_status"] == "IN_TRANSIT"
    assert instrument["unauthorized_move_flag"] is True
    assert instrument["condition_status"] == "NEEDS_ASSESSMENT", (
        "the cascade touches only the custody axis"
    )

    warranty = read_warranty(ctx["warranty"]["id"])
    assert warranty["status"] == "VOIDED"
    assert warranty["void_reason"] == "UNAUTHORIZED_MOVE"

    claim = validate_success(api.get_warranty_claim(ctx["claim"]["id"], MANAGER))
    assert claim["status"] == "DENIED"


def test_unauthorized_move_reverses_the_provisional_credit(api):
    """PRD 2.11: "Hop 4: *because* a claim was denied, a `REVERSAL` ledger row is
    appended carrying the negation of that claim's provisional `WARRANTY_CREDIT` amount,
    with `reverses_entry_id` pointing at the original row, which is never mutated. Hop
    5: *because* the ledger changed, the client's `account_credit_cents` is recomputed
    as the plain sum over all of that client's rows and the client's `version` is
    incremented by 1."
    PRD 2.10: "Ledger rows are append-only and immutable: a reversal never edits or
    hides the original row, it appends the negation with `reverses_entry_id` pointing at
    the row it undoes."

    Design: Difficulty/transitive_cascade/cascade_a_unauthorized_move_depth_five
    """
    ctx = setup_submitted_warranty_claim()
    client_id = ctx["client"]["id"]

    validate_success(
        api.create_custody_transition(
            ctx["instrument"]["id"], {"to_custody_status": "IN_TRANSIT"}, COORDINATOR
        )
    )

    rows = read_ledger(client_id)
    credit = next(r for r in rows if r["entry_type"] == "WARRANTY_CREDIT")
    reversals = [r for r in rows if r["entry_type"] == "REVERSAL"]
    assert len(reversals) == 1
    assert reversals[0]["amount_cents"] == -8666
    assert reversals[0]["reverses_entry_id"] == credit["id"]
    assert credit["amount_cents"] == 8666, "the forward row was never mutated"

    client = read_client(client_id)
    assert client["account_credit_cents"] == 80500
    assert_client_money_conservation(client, rows)


def test_manual_void_denies_the_claim_and_reverses_its_credit_row(api):
    """PRD 3.9: "Or it is **voided**, which can happen four ways: a `ShopManager` voids
    it explicitly by supplying a `void_reason`; the unauthorized-move cascade voids it
    with reason `UNAUTHORIZED_MOVE`; the lapsed-recall sweep voids it with reason
    `TUNING_CYCLE_LAPSED`; and the climate gate on claim filing voids it with reason
    `CLIMATE_OUT_OF_BAND`."
    PRD 3.9: "Every void — whatever its origin — denies the warranty's open claims, as
    Cascade A hops 3 through 5 describe."
    PRD 2.12: "The balance sum is order-independent, but the `created_at` sequence is
    observable through the ledger listing, which returns rows in `created_at` ascending
    order."

    Design: Difficulty/compensating_invariant/client_ledger_conservation_across_credit_and_reversal
    """
    ctx = setup_submitted_warranty_claim()
    client_id = ctx["client"]["id"]
    assert read_client(client_id)["account_credit_cents"] == 89166

    validate_success(
        api.void_warranty(ctx["warranty"]["id"], {"void_reason": "MANUAL"}, MANAGER)
    )

    warranty = read_warranty(ctx["warranty"]["id"])
    assert warranty["status"] == "VOIDED"
    assert warranty["void_reason"] == "MANUAL"

    claim = validate_success(api.get_warranty_claim(ctx["claim"]["id"], MANAGER))
    assert claim["status"] == "DENIED"

    rows = read_ledger(client_id)
    assert [r["amount_cents"] for r in rows] == [100000, -19500, 8666, -8666]
    reversal = rows[-1]
    credit = rows[-2]
    assert reversal["entry_type"] == "REVERSAL"
    assert reversal["reverses_entry_id"] == credit["id"]
    assert reversal["warranty_claim_id"] == ctx["claim"]["id"]


def test_the_reversal_returns_the_balance_to_where_it_started(api):
    """PRD 2.10: "**Client money.** For every client, `account_credit_cents` equals the
    plain sum of `amount_cents` over **every** ledger row carrying that client's
    `client_id`, with no status filter of any kind."
    PRD 2.10: "A forward entry paired with its reversal therefore leaves the balance
    exactly where it started."

    Design: Difficulty/compensating_invariant/client_ledger_conservation_across_credit_and_reversal
    """
    ctx = setup_submitted_warranty_claim()
    client_id = ctx["client"]["id"]

    validate_success(
        api.void_warranty(ctx["warranty"]["id"], {"void_reason": "MANUAL"}, MANAGER)
    )

    rows = read_ledger(client_id)
    client = read_client(client_id)
    assert client["account_credit_cents"] == 80500, (
        "exactly the value held before the provisional credit was posted"
    )
    assert_client_money_conservation(client, rows)

    credit = next(r for r in rows if r["entry_type"] == "WARRANTY_CREDIT")
    assert credit["amount_cents"] == 8666, "the append-only forward row is never edited"


def test_claim_on_an_out_of_band_address_voids_the_warranty_then_rejects(api):
    """PRD 2.9: "The response is `ERR_CLIMATE_OUT_OF_BAND` (422) and the new
    `WarrantyClaim` row is **not** created. A subsequent read of the warranty observes
    status `VOIDED`, the `CLIMATE_OUT_OF_BAND` reason, and a `version` one higher than
    before the rejected call."
    PRD 2.8: "**Climate gate (mutate-then-reject).** The instrument's current location
    must not carry `out_of_band_flag` true when a warranty claim is filed. Otherwise
    `ERR_CLIMATE_OUT_OF_BAND` (422). Applies to `POST /warranty-claims`."

    Design: Corner/endpoints/warranty_claim_on_out_of_band_location_voids_then_rejects
    """
    ctx = setup_completed_tune_order(funding=100000, climate_controlled=False)
    location, client_id = ctx["location"], ctx["client"]["id"]
    add_climate_reading(location["id"], "2026-04-01T12:00:00Z", 45.0)
    add_climate_reading(location["id"], "2026-04-02T12:00:00Z", 45.0)
    add_climate_reading(location["id"], "2026-04-03T12:00:00Z", 72.0, temperature_f=80.0)
    add_climate_reading(location["id"], "2026-04-04T12:00:00Z", 18.0, temperature_f=55.0)

    location_now = validate_success(api.get_location(location["id"], MANAGER))
    assert location_now["readings_in_window"] == 4
    assert location_now["out_of_band_count"] == 2
    assert location_now["out_of_band_flag"] is True

    warranty_before = read_warranty(ctx["warranty"]["id"])
    response = api.create_warranty_claim(
        warranty_claim_payload(
            warranty_before["id"], warranty_before["version"],
            reported_issue="pitch collapsed",
        ),
        make_client_headers(client_id),
    )
    validate_error(response, ApiErrorId.ERR_CLIMATE_OUT_OF_BAND.value)

    claims, _ = validate_paginated(
        api.list_warranty_claims(MANAGER, params={"warranty_id": warranty_before["id"]})
    )
    assert claims == [], "the claim row was not created"

    warranty_after = read_warranty(warranty_before["id"])
    assert warranty_after["status"] == "VOIDED"
    assert warranty_after["void_reason"] == "CLIMATE_OUT_OF_BAND"
    assert warranty_after["version"] == warranty_before["version"] + 1
    assert warranty_after["claim_count"] == 0
    assert read_client(client_id)["account_credit_cents"] == 80500


def test_the_milestone_releaser_cannot_adjudicate_the_resulting_claim(api):
    """PRD 2.1: "The `X-User-ID` adjudicating a warranty claim must differ from every
    `released_by_user_id` recorded on the milestones of the covered service order, and
    the `X-User-ID` recording a consignment sale must differ from the
    `created_by_user_id` stamped on that agreement when it was drafted. Either violation
    is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 3.9: "**Approval routes by variant**: a claim whose `resolution_variant` is
    `FREE_RESERVICE` lands in `APPROVED_RESERVICE`, and a claim whose variant is
    `PRORATED_CREDIT` lands in `APPROVED_CREDIT`, where the provisional credit simply
    stands and no reversal is appended."

    Design: Corner/rbac/milestone_releaser_cannot_adjudicate_the_resulting_warranty_claim
    """
    ctx = setup_submitted_warranty_claim()
    claim_id = ctx["claim"]["id"]
    releaser = ctx["releaser_user_id"]

    validate_success(
        api.review_warranty_claim(claim_id, make_shop_manager_headers("mgr-reviewer"))
    )

    blocked = api.adjudicate_warranty_claim(
        claim_id, {"decision": "APPROVE"}, make_shop_manager_headers(releaser)
    )
    validate_error(blocked, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    still_open = validate_success(api.get_warranty_claim(claim_id, MANAGER))
    assert still_open["status"] == "UNDER_REVIEW"
    assert still_open["adjudicated_by_user_id"] is None

    approved = validate_success(
        api.adjudicate_warranty_claim(
            claim_id, {"decision": "APPROVE"},
            make_shop_manager_headers("mgr-adjudicator"),
        )
    )
    assert approved["status"] == "APPROVED_CREDIT"
    assert approved["adjudicated_by_user_id"] == "mgr-adjudicator"
    assert read_client(ctx["client"]["id"])["account_credit_cents"] == 89166, (
        "the provisional credit stands under an approval"
    )


def test_second_claim_quoting_a_stale_warranty_version_is_rejected(api):
    """PRD 2.7: "Filing a warranty claim requires `expected_warranty_version` carrying
    the client's last observed `version` of the warranty, and rejects a mismatch with
    `ERR_STALE_WARRANTY_VERSION` (HTTP 412)."
    PRD 3.9: "Filing bumps the warranty's `version` by 1 and its `claim_count` by 1, and
    a warranty already at 2 claims refuses a third with `ERR_ATTEMPT_LIMIT_EXCEEDED`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_warranty_version_on_second_claim
    """
    ctx = setup_completed_tune_order(funding=100000)
    set_clock("2026-06-20T00:00:00Z")
    warranty = read_warranty(ctx["warranty"]["id"])
    stale_version = warranty["version"]

    file_warranty_claim(
        warranty["id"], ctx["client"]["id"], stale_version,
        reported_issue="first complaint",
    )

    response = api.create_warranty_claim(
        warranty_claim_payload(
            warranty["id"], stale_version, reported_issue="second complaint"
        ),
        make_client_headers(ctx["client"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_WARRANTY_VERSION.value)

    assert read_warranty(warranty["id"])["claim_count"] == 1
    claims, _ = validate_paginated(
        api.list_warranty_claims(MANAGER, params={"warranty_id": warranty["id"]})
    )
    assert len(claims) == 1
    assert read_client(ctx["client"]["id"])["account_credit_cents"] == 89166
