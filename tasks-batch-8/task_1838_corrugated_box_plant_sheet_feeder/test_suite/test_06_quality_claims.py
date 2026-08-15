"""Quality claims: FILING vs RESOLUTION credit variants, warp threshold,
terminal lockdown, and segregation of duties."""
import pytest

from test_helpers import (
    CLAIMS_USERS,
    ApiErrorId,
    assert_money,
    assert_msf,
    assert_quality_claim,
    create_claim,
    create_claim_under_review,
    create_resolve_claim_payload,
    make_claims_adjuster_headers,
    setup_invoiced_order_scenario,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADJUDICATOR = TEST_USERS["claims_adjuster_headers"]
FILER_ID = CLAIMS_USERS["FILER_ID"]  # cs-100
ADJ_ID = CLAIMS_USERS["ADJUDICATOR_ID"]  # adj-200


def test_claim_filing_computes_provisional_credit_from_claimed_qty(api):
    """PRD 3.8: "At filing the server snapshots `per_box_price_dollars` — the
    order's `invoice_merchandise_dollars` divided by its `produced_qty`,
    rounded half-up to 4 decimal places — computes the FILING-variant
    `provisional_credit_dollars` as `defective_qty_claimed` times that per-box
    price, rounded half-up to 2 decimal places, and stamps `filed_by_user_id`
    with the filer's `X-User-ID`."

    Design: Difficulty/dual_variant_calc/claim_credit_filing_variant_vs_resolution_variant
    """
    scenario = setup_invoiced_order_scenario(produced_qty=2100)
    order = scenario["order"]
    # invoice_merchandise_dollars 1074.28 / produced 2100 -> 0.5116 per box
    claim = create_claim(
        order["id"], filer_id=FILER_ID, defective_qty_claimed=500
    )
    assert_quality_claim(claim)
    assert claim["status"] == "OPEN"
    assert_msf(claim["per_box_price_dollars"], 0.5116)
    assert_money(claim["provisional_credit_dollars"], 255.80)  # 500 * 0.5116
    assert claim["filed_by_user_id"] == FILER_ID
    assert claim["final_credit_dollars"] is None
    assert claim["adjudicated_by_user_id"] is None


def test_claim_resolution_computes_final_credit_with_capped_freight(api):
    """PRD 3.8: "The RESOLUTION-variant `final_credit_dollars` is then the
    verified quantity times the snapshotted `per_box_price_dollars`, rounded
    half-up to 2 decimal places, plus a freight reimbursement of the documented
    `actual_return_freight_dollars` (treated as 0 when absent) capped at
    500.00 — the lesser of the documented amount and the cap is added. The
    claim lands in `RESOLVED_CREDIT` with `adjudicated_by_user_id` stamped."

    Design: Difficulty/dual_variant_calc/claim_credit_filing_variant_vs_resolution_variant
    """
    scenario = setup_invoiced_order_scenario(produced_qty=2100)
    claim = create_claim_under_review(
        scenario["order"]["id"], filer_id=FILER_ID, defective_qty_claimed=500
    )
    assert_money(claim["provisional_credit_dollars"], 255.80)

    resolved = validate_success(
        api.resolve_quality_claim(
            claim["id"],
            create_resolve_claim_payload(
                outcome="CREDIT",
                defective_qty_verified=400,
                actual_return_freight_dollars=620.00,
            ),
            make_claims_adjuster_headers(ADJ_ID),
        )
    )
    assert resolved["status"] == "RESOLVED_CREDIT"
    # round2(400 * 0.5116) + min(620.00, 500.00) = 204.64 + 500.00
    assert_money(resolved["final_credit_dollars"], 704.64)
    assert resolved["adjudicated_by_user_id"] == ADJ_ID
    assert float(resolved["final_credit_dollars"]) != float(
        resolved["provisional_credit_dollars"]
    ), "RESOLUTION must diverge from FILING when verified != claimed or freight > 0"


def test_resolved_claim_rejects_further_transitions(api, claims_adjuster_headers):
    """PRD 3.8: "A `ClaimsAdjuster` takes an `OPEN` claim into review
    (otherwise `ERR_INVALID_STATE`), moving it to `UNDER_REVIEW`."
    PRD 3.8: "Either way the claim's `version` increments, and both resolution
    states are terminal."

    Design: Corner/state_machines/resolved_claim_terminal_lockdown
    """
    scenario = setup_invoiced_order_scenario(produced_qty=2100)
    claim = create_claim_under_review(
        scenario["order"]["id"], filer_id=FILER_ID, defective_qty_claimed=500
    )
    resolved = validate_success(
        api.resolve_quality_claim(
            claim["id"],
            create_resolve_claim_payload(
                outcome="CREDIT", defective_qty_verified=100
            ),
            make_claims_adjuster_headers(ADJ_ID),
        )
    )
    assert resolved["status"] == "RESOLVED_CREDIT"
    # round2(100 * 0.5116) + 0 freight
    assert_money(resolved["final_credit_dollars"], 51.16)

    res = api.start_claim_review(claim["id"], claims_adjuster_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    # The terminal state and its credit are untouched
    assert resolved["final_credit_dollars"] == pytest.approx(51.16, abs=0.001)


def test_warp_threshold_boundary(api, customer_service_headers):
    """PRD 3.8: "The warp measurement is required exactly when `claim_type` is
    `BOARD_WARP`, and it must be at least 2.0 percent of span, with exactly 2.0
    accepted; a missing or below-threshold measurement is rejected with
    `ERR_WARP_BELOW_THRESHOLD`."

    Design: Corner/validations/warp_threshold_boundary
    """
    scenario = setup_invoiced_order_scenario(produced_qty=2100)
    order = scenario["order"]

    below = api.create_quality_claim(
        {
            "box_order_id": order["id"],
            "claim_type": "BOARD_WARP",
            "defective_qty_claimed": 100,
            "measured_warp_pct": 1.99,
        },
        customer_service_headers,
    )
    validate_error(below, ApiErrorId.ERR_WARP_BELOW_THRESHOLD, expected_status=422)

    at_threshold = api.create_quality_claim(
        {
            "box_order_id": order["id"],
            "claim_type": "BOARD_WARP",
            "defective_qty_claimed": 100,
            "measured_warp_pct": 2.0,
        },
        customer_service_headers,
    )
    claim = validate_success(at_threshold, 201)
    assert claim["status"] == "OPEN"


def test_claim_self_adjudication_rejected(api):
    """PRD 3.8: "Segregation of duties is enforced at this point: the resolving
    operator's `X-User-ID` must differ from the claim's `filed_by_user_id`, and
    a match is rejected with `ERR_SOD_CLAIM_SELF_ADJUDICATION` — the same
    person may not adjudicate a claim they filed, even across roles."

    Design: Corner/validations/sod_self_adjudication_rejected_then_other_adjuster_succeeds
    """
    scenario = setup_invoiced_order_scenario(produced_qty=2100)
    claim = create_claim_under_review(
        scenario["order"]["id"], filer_id=FILER_ID, defective_qty_claimed=500
    )
    assert claim["filed_by_user_id"] == FILER_ID

    # Filer resolving their own claim under the ClaimsAdjuster role
    self_resolve = api.resolve_quality_claim(
        claim["id"],
        create_resolve_claim_payload(
            outcome="CREDIT",
            defective_qty_verified=400,
            actual_return_freight_dollars=620.00,
        ),
        make_claims_adjuster_headers(FILER_ID),
    )
    validate_error(
        self_resolve,
        ApiErrorId.ERR_SOD_CLAIM_SELF_ADJUDICATION,
        expected_status=422,
    )

    # A different adjudicator resolves the same claim
    resolved = validate_success(
        api.resolve_quality_claim(
            claim["id"],
            create_resolve_claim_payload(
                outcome="CREDIT",
                defective_qty_verified=400,
                actual_return_freight_dollars=620.00,
            ),
            make_claims_adjuster_headers(ADJ_ID),
        )
    )
    assert resolved["status"] == "RESOLVED_CREDIT"
    assert_money(resolved["final_credit_dollars"], 704.64)
    assert resolved["adjudicated_by_user_id"] == ADJ_ID
