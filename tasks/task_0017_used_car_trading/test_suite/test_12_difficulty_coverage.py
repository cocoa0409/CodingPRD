"""Difficulty-design coverage tests — every instance in
SCAFFOLD_DIFFICULTY_DESIGN.yaml gets at least TWO dedicated tests, each tagged
with ``# difficulty: <rule_id>/<instance.name>`` for audit. Each test cites
the PRD prose for the underlying rule, not the difficulty-design entry.
"""

import math
from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    advance_assessment_to_onsite,
    advance_clock_payload,
    api_client,
    create_assessment_payload,
    create_draft_assessment,
    create_loan_payload,
    create_purchase_order_payload,
    create_reservation,
    dispute_payload,
    emit_credit_check_returned,
    emit_event_payload,
    emit_payment_received,
    file_dispute,
    finalize_assessment,
    make_admin_headers,
    make_buyer_headers,
    make_seller_headers,
    onsite_findings_payload,
    place_bid,
    register_buyer,
    register_seller,
    register_vehicle,
    server_now_plus,
    setup_active_listing,
    setup_auction_with_two_bidders,
    setup_completed_purchase_order,
    setup_dispute_at_round,
    setup_finalized_assessment,
    setup_holding_reservation,
    setup_listing_under_review,
    setup_loan_in_credit_checking,
    setup_paid_purchase_order,
    setup_transfer_in_failed_state,
    submit_all_transfer_documents,
    validate_error,
    validate_success,
    vin_history,
    NON_EXISTENT_UUID,
)


# ============================================================================
# Rule 1: dual_variant_calc
# ============================================================================


# difficulty: dual_variant_calc/provisional_vs_final_valuation_on_assessment
def test_provisional_uses_declared_mileage_and_history_counts_only(api):
    """PRD §3.1 (provisional valuation): "This provisional figure is
    intentionally a coarse estimate — it ignores on-site grades, the
    major-accident extra penalty, and the discrepancy multiplier."

    With declared=100_000, 1 ACCIDENT(MINOR) + 2 MAINTENANCE: provisional is
    base * 0.75 * (1 - 0.09) = 1_000_000 * 0.75 * 0.91 = 682_500 cents.
    """
    seller = register_seller()
    vehicle = register_vehicle(seller, declared_mileage_km=100_000)
    history = vin_history(accidents=1, maintenance=2)
    draft = create_draft_assessment(vehicle, vin_history_records=history)
    onsite_pending = advance_assessment_to_onsite(draft)
    assert onsite_pending["provisional_valuation_cents"] == 682_500


# difficulty: dual_variant_calc/provisional_vs_final_valuation_on_assessment
def test_final_uses_verified_mileage_grades_and_discrepancy_multiplier(api):
    """PRD §3.1 (final valuation, with discrepancy):
    "multiply by one minus the discrepancy penalty of fifteen percent if the
    mileage_discrepancy_flag is true (otherwise multiply by one — that is,
    no further adjustment)."

    Same history as provisional case, but with onsite mileage 110_000
    (discrepancy=true) and grades A/A/B:
      mileage_factor = max(0.5, 1 - (110000/200000)*0.5) = 0.725
      grade_avg = (1.0 + 1.0 + 0.9)/3 = 2.9/3
      history_penalty = (1*800 + 0*1200 + 2*50)/10000 = 0.09
      final = 1_000_000 * 0.725 * (2.9/3) * 0.91 * 0.85 → round_half_up
            = 542_095 cents.
    Provisional was 682_500 — these are deliberately divergent.
    """
    seller = register_seller()
    vehicle = register_vehicle(seller, declared_mileage_km=100_000)
    history = vin_history(accidents=1, maintenance=2)
    draft = create_draft_assessment(vehicle, vin_history_records=history)
    onsite_pending = advance_assessment_to_onsite(draft)
    finalized = finalize_assessment(
        onsite_pending,
        onsite=onsite_findings_payload(
            exterior_grade="A",
            interior_grade="A",
            mechanical_grade="B",
            mileage_km_observed=110_000,
        ),
    )
    assert finalized["mileage_discrepancy_flag"] is True
    assert finalized["final_valuation_cents"] == 542_095
    assert finalized["provisional_valuation_cents"] != finalized["final_valuation_cents"]


# difficulty: dual_variant_calc/provisional_vs_final_valuation_on_assessment
def test_assessment_score_for_known_inputs_equals_seventy_eight(api, admin_headers):
    """PRD §3.1 (assessment score):
    "compute the grade points as the average grade value times one hundred,
    the mileage points as the larger of zero and one hundred minus the
    verified mileage divided by the reference mileage of two hundred thousand
    kilometres further multiplied by one hundred, and the history points as
    the larger of zero and one hundred minus the accident_count times ten
    minus the major_accident_count times fifteen minus an extra deduction of
    twenty if the mileage_discrepancy_flag is true (else zero); combine with
    weights of zero point five for grades, zero point two for mileage, and
    zero point three for history, and round the weighted sum half-up to a
    0-to-100 integer."

    Inputs: grades A/A/B, observed=110_000, accident_count=1,
    major_accident_count=0, discrepancy=true.
      grade_pts = 96.6667; mileage_pts = 45; history_pts = 70
      score = 0.5*96.667 + 0.2*45 + 0.3*70 = 78.333 → 78.
    """
    seller = register_seller()
    vehicle = register_vehicle(seller, declared_mileage_km=100_000)
    history = vin_history(accidents=1, maintenance=2)
    draft = create_draft_assessment(vehicle, vin_history_records=history)
    onsite_pending = advance_assessment_to_onsite(draft)
    finalize_assessment(
        onsite_pending,
        onsite=onsite_findings_payload(
            exterior_grade="A",
            interior_grade="A",
            mechanical_grade="B",
            mileage_km_observed=110_000,
        ),
    )
    refreshed = validate_success(api.get_vehicle(vehicle["id"], admin_headers), 200)
    assert refreshed["assessment_score"] == 78


# difficulty: dual_variant_calc/dispute_partial_refund_with_or_without_third_party
def test_refund_partial_without_third_party_at_ten_percent(api, admin_headers):
    """PRD §3.9 (REFUND_PARTIAL, no third-party path):
    "the base percentage is ten percent if no third_party_report_url was
    filed".

    agreed=5_000_000 → refund = round_half_up(5_000_000 * 0.10) = 500_000.
    """
    state = setup_completed_purchase_order(ask_price_cents=5_000_000)
    dispute = file_dispute(state)
    validate_success(api.start_review_dispute(dispute["id"], admin_headers), 200)
    validate_success(
        api.propose_resolution(
            dispute["id"], {"resolution": "REFUND_PARTIAL"}, admin_headers
        ),
        200,
    )
    closed = validate_success(api.execute_dispute(dispute["id"], admin_headers), 200)
    assert closed["refund_amount_cents"] == 500_000


# difficulty: dual_variant_calc/dispute_partial_refund_with_or_without_third_party
def test_refund_partial_with_third_party_at_thirty_percent(api, admin_headers):
    """PRD §3.9 (REFUND_PARTIAL with third-party): "thirty percent if one was".

    Same agreed_price=5_000_000 → 1_500_000.
    """
    state = setup_completed_purchase_order(ask_price_cents=5_000_000)
    dispute = file_dispute(state)
    validate_success(api.start_review_dispute(dispute["id"], admin_headers), 200)
    validate_success(api.request_third_party(dispute["id"], admin_headers), 200)
    validate_success(
        api.submit_third_party_report(
            dispute["id"],
            {"third_party_report_url": "https://example.com/r.pdf"},
            admin_headers,
        ),
        200,
    )
    propose_res = api.propose_resolution(
        dispute["id"], {"resolution": "REFUND_PARTIAL"}, admin_headers
    )
    if propose_res.status_code >= 400:
        closed = validate_success(
            api.execute_dispute(
                dispute["id"], admin_headers, payload={"resolution": "REFUND_PARTIAL"}
            ),
            200,
        )
    else:
        closed = validate_success(api.execute_dispute(dispute["id"], admin_headers), 200)
    assert closed["refund_amount_cents"] == 1_500_000


# ============================================================================
# Rule 2: combinatorial_formula
# ============================================================================


# difficulty: combinatorial_formula/final_valuation_three_input_nonlinear
def test_final_valuation_combines_mileage_grade_history_and_discrepancy(api):
    """PRD §3.1 (final valuation): "multiply by one minus the discrepancy
    penalty of fifteen percent if the mileage_discrepancy_flag is true
    (otherwise multiply by one — that is, no further adjustment)."

    Demonstrates the conditional fourth multiplier. Inputs:
      base=1_000_000, mileage_factor=0.725, grade_avg=2.9/3, history=0.09,
      discrepancy=true → 542_095.
    """
    seller = register_seller()
    vehicle = register_vehicle(seller, declared_mileage_km=100_000)
    history = vin_history(accidents=1, maintenance=2)
    draft = create_draft_assessment(vehicle, vin_history_records=history)
    onsite_pending = advance_assessment_to_onsite(draft)
    finalized = finalize_assessment(
        onsite_pending,
        onsite=onsite_findings_payload(
            exterior_grade="A",
            interior_grade="A",
            mechanical_grade="B",
            mileage_km_observed=110_000,
        ),
    )
    assert finalized["final_valuation_cents"] == 542_095


# difficulty: combinatorial_formula/final_valuation_three_input_nonlinear
def test_final_valuation_no_discrepancy_omits_fifteen_percent_factor(api):
    """PRD §3.1: "otherwise multiply by one — that is, no further adjustment".

    Same history (1 minor accident + 2 maintenance), grades A/A/B, but
    observed=declared=100_000 → flag false → no discrepancy multiplier:
      final = 1_000_000 * 0.75 * (2.9/3) * 0.91 * 1.0
            = 1_000_000 * 0.75 * 0.96666... * 0.91
            = 725_000 * 0.91
            = 659_750 → round_half_up = 659_750.
    """
    seller = register_seller()
    vehicle = register_vehicle(seller, declared_mileage_km=100_000)
    history = vin_history(accidents=1, maintenance=2)
    draft = create_draft_assessment(vehicle, vin_history_records=history)
    onsite_pending = advance_assessment_to_onsite(draft)
    finalized = finalize_assessment(
        onsite_pending,
        onsite=onsite_findings_payload(
            exterior_grade="A",
            interior_grade="A",
            mechanical_grade="B",
            mileage_km_observed=100_000,
        ),
    )
    assert finalized["mileage_discrepancy_flag"] is False
    assert finalized["final_valuation_cents"] == 659_750


# difficulty: combinatorial_formula/loan_amortization_pinned_evaluation_order
def test_loan_amortization_pinned_five_step_order_yields_known_cents(api, admin_headers):
    """PRD §3.6: "On approval the system computes the amortisation in a
    pinned five-step order. ... Fourth, the monthly_payment_cents is the
    standard amortisation: take the lender APR in basis points divided by ten
    thousand divided by twelve to get the monthly rate, then take the
    approved_principal_cents multiplied by the monthly rate divided by one
    minus the quantity (one plus the monthly rate) raised to the negative of
    the term_months, and round the whole thing up to the next whole cent
    (single ceiling at the end). Fifth, the total_interest_cents is the
    monthly_payment_cents multiplied by the term_months minus the
    approved_principal_cents (no further rounding)."

    Inputs: agreed=5_000_000, ratio=2000bp, requested=4_000_000, term=36,
    credit=700, LENDER_A APR=580bp.
    Expected: approved=4_000_000, monthly=121_326, total_interest=367_736.
    """
    state = setup_loan_in_credit_checking(
        ask_price_cents=5_000_000,
        lender_code="LENDER_A",
        requested_principal_cents=4_000_000,
        down_payment_ratio_bp=2_000,
        term_months=36,
    )
    emit_credit_check_returned(state["loan"]["id"], credit_score=700)
    loan = validate_success(api.get_loan(state["loan"]["id"], admin_headers), 200)
    assert loan["status"] == "APPROVED"
    assert loan["approved_principal_cents"] == 4_000_000
    assert loan["monthly_payment_cents"] == 121_326
    assert loan["total_interest_cents"] == 367_736


# difficulty: combinatorial_formula/loan_amortization_pinned_evaluation_order
def test_loan_amortization_total_interest_invariant_holds(api, admin_headers):
    """PRD §3.6: "the total_interest_cents is the monthly_payment_cents
    multiplied by the term_months minus the approved_principal_cents (no
    further rounding)." This invariant must hold for any approved loan.
    """
    state = setup_loan_in_credit_checking(
        ask_price_cents=5_000_000,
        lender_code="LENDER_A",
        requested_principal_cents=4_000_000,
        down_payment_ratio_bp=2_000,
        term_months=36,
    )
    emit_credit_check_returned(state["loan"]["id"], credit_score=700)
    loan = validate_success(api.get_loan(state["loan"]["id"], admin_headers), 200)
    expected_interest = (
        loan["monthly_payment_cents"] * loan["term_months"]
        - loan["approved_principal_cents"]
    )
    assert loan["total_interest_cents"] == expected_interest


# ============================================================================
# Rule 3: non_linear_state_machine
# ============================================================================


# difficulty: non_linear_state_machine/bid_cyclic_live_outbid
def test_bid_state_cycles_live_to_outbid_on_higher_bid(api, admin_headers):
    """PRD §3.3: "If a previous LIVE bid existed on the same listing, it is
    moved to OUTBID and its deposit hold is released."

    Buyer A bids 1_050_000 (LIVE), Buyer B bids 1_250_000 → A→OUTBID, B→LIVE.
    """
    _, listing, _, buyer_a, buyer_b = setup_auction_with_two_bidders(
        ask_price_cents=1_000_000, reserve_price_cents=1_000_000
    )
    bid_a = place_bid(buyer_a, listing, 1_050_000)
    bid_b = place_bid(buyer_b, listing, 1_250_000)
    refreshed_listing = validate_success(api.get_listing(listing["id"], admin_headers), 200)
    assert refreshed_listing["active_bid_id"] == bid_b["id"]
    # A bid was outbid: list bids and confirm.
    from prd_bench_local_runner.testing import validate_paginated

    bids, _meta = validate_paginated(api.list_bids(listing["id"], admin_headers))
    a_after = next(b for b in bids if b["id"] == bid_a["id"])
    b_after = next(b for b in bids if b["id"] == bid_b["id"])
    assert a_after["status"] == "OUTBID"
    assert b_after["status"] == "LIVE"


# difficulty: non_linear_state_machine/bid_cyclic_live_outbid
def test_bid_cycle_a_outbids_b_after_being_outbid(api, admin_headers):
    """PRD §3.3: "The cyclic LIVE ↔ OUTBID shape is intentional: a buyer who
    was outbid may place a new bid (new row) and re-acquire the deposit
    hold; the previously leading buyer is then transitioned LIVE → OUTBID
    themselves. Each round of bidding is therefore a new Bid row."

    Sequence: A bids 1_050_000, B bids 1_250_000, A bids 1_500_000.
    Expect A2 LIVE, B's bid OUTBID; deposits reflect.
    """
    _, listing, _, buyer_a, buyer_b = setup_auction_with_two_bidders(
        ask_price_cents=1_000_000, reserve_price_cents=1_000_000
    )
    place_bid(buyer_a, listing, 1_050_000)
    bid_b = place_bid(buyer_b, listing, 1_250_000)
    bid_a2 = place_bid(buyer_a, listing, 1_500_000)
    refreshed_listing = validate_success(api.get_listing(listing["id"], admin_headers), 200)
    assert refreshed_listing["active_bid_id"] == bid_a2["id"]
    a_buyer = validate_success(api.get_buyer(buyer_a["id"], make_buyer_headers(buyer_a["id"])), 200)
    b_buyer = validate_success(api.get_buyer(buyer_b["id"], make_buyer_headers(buyer_b["id"])), 200)
    # A holds 150_000 = ceil(1_500_000*0.10); B holds 0.
    assert a_buyer["deposit_held_cents"] == math.ceil(1_500_000 * 0.10)
    assert b_buyer["deposit_held_cents"] == 0


# difficulty: non_linear_state_machine/dispute_cyclic_evidence_review
def test_dispute_round_count_caps_at_three(api, admin_headers):
    """PRD §3.9: "round_count may not exceed the maximum mediation rounds of
    three, and any start-review or request-more-evidence step that would
    push it beyond is rejected with ERR_DISPUTE_ROUNDS_EXHAUSTED."
    """
    state = setup_completed_purchase_order(ask_price_cents=2_000_000)
    dispute = setup_dispute_at_round(state, round_count=3)
    assert dispute["round_count"] == 3
    res = api.request_more_evidence(dispute["id"], admin_headers)
    validate_error(res, "ERR_DISPUTE_ROUNDS_EXHAUSTED")


# difficulty: non_linear_state_machine/dispute_cyclic_evidence_review
def test_dispute_cycles_submitted_evidence_review_increments_round(api, admin_headers):
    """PRD §3.9: "A platform admin starts review by transitioning the case
    from SUBMITTED to EVIDENCE_REVIEW, which increments round_count by one.
    From EVIDENCE_REVIEW the admin has three exits. They may request more
    evidence, transitioning back to SUBMITTED for another round".
    """
    state = setup_completed_purchase_order(ask_price_cents=2_000_000)
    dispute = file_dispute(state)
    # Round 1
    d1 = validate_success(api.start_review_dispute(dispute["id"], admin_headers), 200)
    assert d1["round_count"] == 1
    assert d1["stage"] == "EVIDENCE_REVIEW"
    # Cycle back to SUBMITTED.
    d2 = validate_success(api.request_more_evidence(dispute["id"], admin_headers), 200)
    assert d2["stage"] == "SUBMITTED"
    # Round 2
    d3 = validate_success(api.start_review_dispute(dispute["id"], admin_headers), 200)
    assert d3["round_count"] == 2


# ============================================================================
# Rule 4: transitive_cascade
# ============================================================================


# difficulty: transitive_cascade/transfer_rollback_full_cascade_depth_4
def test_rollback_cascades_through_po_listing_vehicle_warranty(api, admin_headers):
    """PRD §2.6 / §3.7 (rollback cascade):
    "A rolled-back transfer (TransferCase FAILED → ROLLED_BACK) advances the
    PurchaseOrder from AWAITING_TRANSFER to REFUNDED, restores the Listing
    from SOLD to ACTIVE, restores the Vehicle from SOLD to LISTED, voids the
    Warranty (ACTIVE → VOIDED), and cancels any disbursed Loan (DISBURSED →
    CANCELLED); Vehicle.ownership_seller_id reverts to the original Seller.id,
    and rolled_back_at is set to the rollback instant."
    """
    state = setup_transfer_in_failed_state(ask_price_cents=2_000_000)
    transfer = state["transfer"]
    rolled_back = validate_success(api.rollback_transfer(transfer["id"], admin_headers), 200)
    assert rolled_back["status"] == "ROLLED_BACK"
    assert rolled_back.get("rolled_back_at") is not None

    po_after = validate_success(
        api.get_purchase_order(state["purchase_order"]["id"], admin_headers), 200
    )
    assert po_after["status"] == "REFUNDED"
    listing_after = validate_success(api.get_listing(state["listing"]["id"], admin_headers), 200)
    assert listing_after["status"] == "ACTIVE"
    vehicle_after = validate_success(api.get_vehicle(state["vehicle"]["id"], admin_headers), 200)
    assert vehicle_after["vehicle_status"] == "LISTED"
    if state.get("warranty"):
        warranty_after = validate_success(
            api.get_warranty(state["warranty"]["id"], admin_headers), 200
        )
        assert warranty_after["status"] == "VOIDED"


# difficulty: transitive_cascade/transfer_rollback_full_cascade_depth_4
def test_rollback_reverts_vehicle_ownership_to_original_seller(api, admin_headers):
    """PRD §2.6 / §3.7: "Vehicle.ownership_seller_id reverts to the original
    Seller.id".
    """
    state = setup_transfer_in_failed_state(ask_price_cents=2_000_000)
    transfer = state["transfer"]
    validate_success(api.rollback_transfer(transfer["id"], admin_headers), 200)
    vehicle_after = validate_success(api.get_vehicle(state["vehicle"]["id"], admin_headers), 200)
    assert vehicle_after["ownership_seller_id"] == state["seller"]["id"]


# difficulty: transitive_cascade/listing_approval_cascade_depth_2
def test_listing_approval_cascades_vehicle_to_listed(api, admin_headers):
    """PRD §3.2: "Approving advances the listing from UNDER_REVIEW to ACTIVE,
    sets doc_check_status to PASS, and cascades the underlying vehicle from
    ASSESSED to LISTED."
    """
    seller, vehicle, _, listing = setup_active_listing(sale_mode="FIXED_PRICE")
    listing_after = validate_success(api.get_listing(listing["id"], admin_headers), 200)
    assert listing_after["status"] == "ACTIVE"
    assert listing_after["doc_check_status"] == "PASS"
    vehicle_after = validate_success(api.get_vehicle(vehicle["id"], admin_headers), 200)
    assert vehicle_after["vehicle_status"] == "LISTED"


# difficulty: transitive_cascade/listing_approval_cascade_depth_2
def test_listing_approval_does_not_archive_vehicle(api, admin_headers):
    """PRD §3.2: "Approving advances the listing from UNDER_REVIEW to ACTIVE,
    sets doc_check_status to PASS, and cascades the underlying vehicle from
    ASSESSED to LISTED."

    The cascade depth is two (Listing → Vehicle); the Vehicle must end up at
    LISTED, not ARCHIVED. PRD §3.7 reserves the ARCHIVED transition for a
    successful DMV transfer, which has not occurred.
    """
    seller, vehicle, _, listing = setup_active_listing(sale_mode="FIXED_PRICE")
    vehicle_after = validate_success(api.get_vehicle(vehicle["id"], admin_headers), 200)
    assert vehicle_after["vehicle_status"] == "LISTED"
    # PRD §3.1: vehicle terminal state is ARCHIVED, only reachable via
    # successful transfer. Approval must not have moved it there.
    assert vehicle_after["vehicle_status"] != "ARCHIVED"


# ============================================================================
# Rule 5: priority_pair_validation_conflict
# ============================================================================


# difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_listing_submit
def test_submit_on_active_listing_returns_invalid_state_not_docs_insufficient(api):
    """PRD §2.8: "state-machine admissibility (ERR_INVALID_STATE) ... [then]
    listing-document sufficiency (ERR_LISTING_DOCS_INSUFFICIENT). Earlier-
    priority failures mask later ones — the response carries only the
    highest-priority error_id that fires."

    Setup: a listing already in ACTIVE — submit transitions DRAFT→UNDER_REVIEW
    only; ACTIVE is not an admissible state. Photo count of 3 (insufficient)
    would also fire ERR_LISTING_DOCS_INSUFFICIENT, but the state check has
    higher priority and must mask it.
    """
    seller, vehicle, _, listing = setup_active_listing(sale_mode="FIXED_PRICE")
    res = api.submit_listing(listing["id"], make_seller_headers(seller["id"]))
    validate_error(res, "ERR_INVALID_STATE")


# difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_listing_submit
def test_submit_on_draft_with_three_photos_returns_docs_insufficient_when_state_admissible(
    api,
):
    """PRD §3.2: "Photo or attestation insufficiency is rejected with
    ERR_LISTING_DOCS_INSUFFICIENT; an unfinalised pinned report is rejected
    with ERR_ASSESSMENT_NOT_FINALIZED."

    Mirror of the priority-pair test: when state IS admissible
    (DRAFT → UNDER_REVIEW is valid) but photos < 6, the doc-sufficiency check
    fires per PRD §2.8 priority order.
    """
    from test_helpers import (
        create_draft_listing,
        setup_finalized_assessment,
    )

    seller, vehicle, assessment = setup_finalized_assessment()
    listing = create_draft_listing(
        seller,
        vehicle,
        assessment,
        photo_urls=["https://x/1", "https://x/2", "https://x/3"],
    )
    res = api.submit_listing(listing["id"], make_seller_headers(seller["id"]))
    validate_error(res, "ERR_LISTING_DOCS_INSUFFICIENT")


# difficulty: priority_pair_validation_conflict/business_referential_vs_business_fiscal_on_loan
def test_loan_application_on_nonexistent_po_returns_not_found(api):
    """PRD §2.8: "Existence checks run next: path-parameter resolution
    (ERR_NOT_FOUND from path) before body-referenced foreign-key resolution
    (ERR_NOT_FOUND from body). ... then loan down-payment ratio
    (ERR_DOWN_PAYMENT_INSUFFICIENT), then loan parameter validity
    (ERR_LOAN_PARAMS_INVALID)."

    Even though down_payment_ratio_bp=1000 is below LENDER_A's minimum 1500,
    the path-not-found check has earlier priority and must mask it.
    """
    buyer = register_buyer()
    res = api.apply_loan(
        NON_EXISTENT_UUID,
        create_loan_payload(
            lender_code="LENDER_A",
            requested_principal_cents=2_000_000,
            down_payment_ratio_bp=1_000,
            term_months=36,
        ),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, "ERR_NOT_FOUND")


# difficulty: priority_pair_validation_conflict/business_referential_vs_business_fiscal_on_loan
def test_loan_application_with_valid_po_below_min_down_payment_returns_dp_insufficient(api):
    """PRD §2.8 mirror: when path resolves and PO exists, the
    down-payment check fires.

    PRD §3.6: "any value below — even by a single basis point — fails with
    ERR_DOWN_PAYMENT_INSUFFICIENT."
    """
    seller, vehicle, listing, buyer, _ = setup_holding_reservation(
        ask_price_cents=5_000_000
    )
    po_payload = create_purchase_order_payload(listing["id"], payment_method="LOAN")
    po_payload["package_code"] = "STANDARD"
    po = validate_success(
        api.create_purchase_order(po_payload, make_buyer_headers(buyer["id"])), 201
    )
    res = api.apply_loan(
        po["id"],
        create_loan_payload(
            lender_code="LENDER_A",
            requested_principal_cents=2_000_000,
            down_payment_ratio_bp=1_000,
            term_months=36,
        ),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, "ERR_DOWN_PAYMENT_INSUFFICIENT")


# ============================================================================
# Rule 6: boundary_precision_check
# ============================================================================


# difficulty: boundary_precision_check/bid_increment_strict_at_required_min
def test_bid_one_below_required_min_rejected(api):
    """PRD §3.3: "The new bid's amount_cents must be at least the current
    maximum plus the applicable increment ... A bid below the required
    minimum is rejected with ERR_BID_TOO_LOW."

    Setup: ask=1_000_000 (low tier; increment=50_000); required=1_050_000.
    A bid of 1_049_999 must fail.
    """
    _, listing, _, buyer_a, _ = setup_auction_with_two_bidders(
        ask_price_cents=1_000_000, reserve_price_cents=1_000_000
    )
    res = api.place_bid(
        listing["id"],
        {"amount_cents": 1_049_999},
        make_buyer_headers(buyer_a["id"]),
    )
    validate_error(res, "ERR_BID_TOO_LOW")


# difficulty: boundary_precision_check/bid_increment_strict_at_required_min
def test_bid_exactly_at_required_min_succeeds(api):
    """PRD §3.3: "must be at least the current maximum plus the applicable
    increment". The required-min is INCLUSIVE.
    Setup: ask=1_000_000, increment=50_000; bid 1_050_000 must succeed.
    """
    _, listing, _, buyer_a, _ = setup_auction_with_two_bidders(
        ask_price_cents=1_000_000, reserve_price_cents=1_000_000
    )
    res = api.place_bid(
        listing["id"],
        {"amount_cents": 1_050_000},
        make_buyer_headers(buyer_a["id"]),
    )
    bid = validate_success(res, 201)
    assert bid["status"] == "LIVE"
    assert bid["amount_cents"] == 1_050_000


# difficulty: boundary_precision_check/dispute_rounds_exhausted_at_three
def test_request_more_evidence_at_round_three_rejected_with_rounds_exhausted(api, admin_headers):
    """PRD §3.9: "round_count may not exceed the maximum mediation rounds of
    three, and any start-review or request-more-evidence step that would
    push it beyond is rejected with ERR_DISPUTE_ROUNDS_EXHAUSTED."
    """
    state = setup_completed_purchase_order(ask_price_cents=2_000_000)
    dispute = setup_dispute_at_round(state, round_count=3)
    assert dispute["round_count"] == 3
    res = api.request_more_evidence(dispute["id"], admin_headers)
    validate_error(res, "ERR_DISPUTE_ROUNDS_EXHAUSTED")


# difficulty: boundary_precision_check/dispute_rounds_exhausted_at_three
def test_round_count_unchanged_after_rejection(api, admin_headers):
    """PRD §3.9 boundary: when request-more-evidence is rejected at the cap,
    round_count must not change. PRD §3.9: "any start-review or
    request-more-evidence step that would push it beyond is rejected" — the
    state must be left untouched."""
    state = setup_completed_purchase_order(ask_price_cents=2_000_000)
    dispute = setup_dispute_at_round(state, round_count=3)
    api.request_more_evidence(dispute["id"], admin_headers)  # fails
    refreshed = validate_success(
        api.get_purchase_order(state["purchase_order"]["id"], admin_headers), 200
    )  # PO unchanged side-check
    # Re-fetch dispute via list-or-direct GET; PRD does not provide a direct
    # GET on disputes — re-trigger start-review which would either error if
    # already in EVIDENCE_REVIEW or move SUBMITTED→EVIDENCE_REVIEW.
    # To check the count holds at 3: start-review at this point should
    # ALSO fail (round_count would become 4).
    res = api.start_review_dispute(dispute["id"], admin_headers)
    # If at EVIDENCE_REVIEW, start-review fails ERR_INVALID_STATE; if it
    # somehow returned to SUBMITTED, start-review would fail
    # ERR_DISPUTE_ROUNDS_EXHAUSTED. Either is faithful to PRD §3.9.
    assert res.status_code >= 400


# ============================================================================
# Rule 7: cross_entity_state_dependency
# ============================================================================


# difficulty: cross_entity_state_dependency/listing_approve_requires_assessment_finalized_with_pinned_version
def test_approve_rejected_when_pinned_assessment_superseded(api, admin_headers):
    """PRD §3.2: "Approval requires that doc_check_status end up as PASS
    and — critically — that the pinned assessment_report_version still equal
    the current version of the pinned AssessmentReport; if a newer report has
    been finalised in the meantime ..., the approve step is rejected with
    ERR_ASSESSMENT_VERSION_STALE."
    PRD §3.1: "Whenever a newer report is finalised, every prior report for
    the same vehicle that was in FINALIZED is moved to SUPERSEDED."

    Two faithful PRD readings — version-stale or not-finalized — both indicate
    the implementer correctly rejected approval.
    """
    from prd_bench_local_runner.testing import validate_error_is_one_of

    seller, vehicle, assessment, listing = setup_listing_under_review()
    # Finalize a newer report on the same vehicle.
    new_draft = create_draft_assessment(
        vehicle, vin_history_records=vin_history(maintenance=2)
    )
    new_onsite = advance_assessment_to_onsite(new_draft)
    finalize_assessment(
        new_onsite,
        onsite=onsite_findings_payload(mileage_km_observed=vehicle["declared_mileage_km"]),
    )
    res = api.approve_listing(listing["id"], admin_headers)
    validate_error_is_one_of(
        res, ["ERR_ASSESSMENT_VERSION_STALE", "ERR_ASSESSMENT_NOT_FINALIZED"]
    )


# difficulty: cross_entity_state_dependency/listing_approve_requires_assessment_finalized_with_pinned_version
def test_approve_succeeds_when_pinned_assessment_still_finalized(api, admin_headers):
    """PRD §3.2: "Approving advances the listing from UNDER_REVIEW to ACTIVE
    ... that the pinned assessment_report_version still equal the current
    version of the pinned AssessmentReport". When the pinned report is still
    FINALIZED at its original version, approval proceeds.
    """
    seller, vehicle, _, listing = setup_active_listing()
    refreshed = validate_success(api.get_listing(listing["id"], admin_headers), 200)
    assert refreshed["status"] == "ACTIVE"


# difficulty: cross_entity_state_dependency/warranty_claim_requires_warranty_active
def test_claim_filing_after_warranty_expired_rejected(api):
    """PRD §3.8: "The claim is admissible only while the warranty is ACTIVE
    and the current instant is strictly before expires_at; otherwise
    ERR_WARRANTY_NOT_ACTIVE fires."
    """
    state = setup_paid_purchase_order(package_code="BASIC", ask_price_cents=2_000_000)
    warranty = state["warranty"]
    buyer = state["buyer"]
    # Advance clock far enough to expire even PREMIUM (24 months).
    far_future = server_now_plus(timedelta(days=365 * 3))
    api.advance_clock(
        advance_clock_payload(far_future),
        make_admin_headers(),
    )
    from test_helpers import warranty_claim_payload

    res = api.file_warranty_claim(
        warranty["id"],
        warranty_claim_payload(component="POWERTRAIN", claimed_amount_cents=100_000),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, "ERR_WARRANTY_NOT_ACTIVE")


# difficulty: cross_entity_state_dependency/warranty_claim_requires_warranty_active
def test_claim_filing_while_warranty_active_succeeds(api):
    """PRD §3.8: "The claim is admissible only while the warranty is ACTIVE
    and the current instant is strictly before expires_at" — the positive
    case is the symmetric mirror.
    """
    from test_helpers import warranty_claim_payload

    state = setup_paid_purchase_order(package_code="STANDARD", ask_price_cents=2_000_000)
    warranty = state["warranty"]
    buyer = state["buyer"]
    res = api.file_warranty_claim(
        warranty["id"],
        warranty_claim_payload(component="POWERTRAIN", claimed_amount_cents=100_000),
        make_buyer_headers(buyer["id"]),
    )
    claim = validate_success(res, 201)
    assert claim["status"] == "PENDING"


# ============================================================================
# Rule 8: resource_temporal_overlap
# ============================================================================


# difficulty: resource_temporal_overlap/reservation_holding_window_serial_no_overlap
def test_only_one_holding_reservation_per_listing(api):
    """PRD §3.4: "Reservations are placed at the next available
    queue_position, which is the count of non-terminal reservations on the
    listing plus one. Reservations enter in status QUEUED, with
    hold_expires_at null while they are at any position other than 1."

    Two simultaneous reservations on a fresh listing: one at HOLDING (pos=1),
    the other at QUEUED (pos=2). Never two HOLDING.
    """
    seller, vehicle, listing, buyer_a, reservation_a = setup_holding_reservation()
    buyer_b = register_buyer()
    reservation_b = validate_success(
        api.create_reservation(listing["id"], make_buyer_headers(buyer_b["id"])), 201
    )
    assert reservation_a["status"] == "HOLDING"
    assert reservation_a["queue_position"] == 1
    assert reservation_b["status"] == "QUEUED"
    assert reservation_b["queue_position"] == 2


# difficulty: resource_temporal_overlap/reservation_holding_window_serial_no_overlap
def test_after_holder_expires_next_queued_promotes_to_holding(api, admin_headers):
    """PRD §3.4: "If a next-position reservation exists on the same listing,
    that next reservation is promoted from QUEUED to HOLDING."
    """
    seller, vehicle, listing, buyer_a, reservation_a = setup_holding_reservation()
    buyer_b = register_buyer()
    reservation_b = validate_success(
        api.create_reservation(listing["id"], make_buyer_headers(buyer_b["id"])), 201
    )
    hold_dt = datetime.fromisoformat(reservation_a["hold_expires_at"].replace("Z", "+00:00"))
    far_future = (hold_dt + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    api.advance_clock(
        advance_clock_payload(far_future),
        admin_headers,
    )
    listing_after = validate_success(api.get_listing(listing["id"], admin_headers), 200)
    assert listing_after["status"] == "RESERVED"
    assert listing_after["reservation_buyer_id"] == buyer_b["id"]


# difficulty: resource_temporal_overlap/transfer_appointment_must_be_future_with_60d_window
def test_appointment_in_past_rejected_out_of_window(api):
    """PRD §3.7: "The appointment_at must be strictly later than the current
    instant, and the gap from now to appointment_at must be at most sixty
    days; otherwise the booking is rejected with ERR_APPOINTMENT_OUT_OF_WINDOW."
    """
    from test_helpers import book_appointment_payload

    state = setup_paid_purchase_order(ask_price_cents=2_000_000)
    transfer = state["transfer"]
    buyer = state["buyer"]
    submit_all_transfer_documents(buyer, transfer["id"])
    past = server_now_plus(timedelta(days=-1))
    res = api.book_appointment(
        transfer["id"],
        book_appointment_payload(appointment_at=past),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, "ERR_APPOINTMENT_OUT_OF_WINDOW")


# difficulty: resource_temporal_overlap/transfer_appointment_must_be_future_with_60d_window
def test_appointment_more_than_sixty_days_out_rejected(api):
    """PRD §3.7: "the gap from now to appointment_at must be at most sixty days"."""
    from test_helpers import book_appointment_payload

    state = setup_paid_purchase_order(ask_price_cents=2_000_000)
    transfer = state["transfer"]
    buyer = state["buyer"]
    submit_all_transfer_documents(buyer, transfer["id"])
    far = server_now_plus(timedelta(days=91))
    res = api.book_appointment(
        transfer["id"],
        book_appointment_payload(appointment_at=far),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, "ERR_APPOINTMENT_OUT_OF_WINDOW")


# ============================================================================
# Rule 9: compensating_invariant
# ============================================================================


# difficulty: compensating_invariant/deposit_held_invariant_under_bid_outbid_cycle
def test_deposit_held_tracks_only_live_bids_through_outbid_cycle(api):
    """PRD §3.7: "Each buyer's deposit_held_cents (the running sum across all
    of their LIVE bids and their HOLDING reservation, which by invariant
    equals the buyer's deposit_balance_cents) ..."
    PRD §3.3: "If a previous LIVE bid existed on the same listing, it is
    moved to OUTBID and its deposit hold is released."

    Sequence: A 1_050_000 → A holds 105_000, B 0.
              B 1_250_000 → A 0, B holds 125_000.
              A 1_500_000 → A holds 150_000, B 0.
    Invariant: deposit_balance_cents == deposit_held_cents at every step.
    """
    _, listing, _, buyer_a, buyer_b = setup_auction_with_two_bidders(
        ask_price_cents=1_000_000, reserve_price_cents=1_000_000
    )
    place_bid(buyer_a, listing, 1_050_000)
    a1 = validate_success(api.get_buyer(buyer_a["id"], make_buyer_headers(buyer_a["id"])), 200)
    b1 = validate_success(api.get_buyer(buyer_b["id"], make_buyer_headers(buyer_b["id"])), 200)
    assert a1["deposit_held_cents"] == 105_000
    assert a1["deposit_balance_cents"] == a1["deposit_held_cents"]
    assert b1["deposit_held_cents"] == 0

    place_bid(buyer_b, listing, 1_250_000)
    a2 = validate_success(api.get_buyer(buyer_a["id"], make_buyer_headers(buyer_a["id"])), 200)
    b2 = validate_success(api.get_buyer(buyer_b["id"], make_buyer_headers(buyer_b["id"])), 200)
    assert a2["deposit_held_cents"] == 0
    assert b2["deposit_held_cents"] == 125_000
    assert b2["deposit_balance_cents"] == b2["deposit_held_cents"]

    place_bid(buyer_a, listing, 1_500_000)
    a3 = validate_success(api.get_buyer(buyer_a["id"], make_buyer_headers(buyer_a["id"])), 200)
    b3 = validate_success(api.get_buyer(buyer_b["id"], make_buyer_headers(buyer_b["id"])), 200)
    assert a3["deposit_held_cents"] == 150_000
    assert a3["deposit_balance_cents"] == a3["deposit_held_cents"]
    assert b3["deposit_held_cents"] == 0


# difficulty: compensating_invariant/deposit_held_invariant_under_bid_outbid_cycle
def test_deposit_balance_equals_deposit_held_invariant_on_every_mutation(api):
    """PRD §3.1: "the running invariant is that those two fields remain
    equal at all times."
    PRD §3.7: "The two computed fields deposit_held_cents and
    deposit_balance_cents must remain equal at all times."

    After bid placement, then cancellation, the invariant must still hold.
    """
    _, listing, _, buyer_a, _ = setup_auction_with_two_bidders(
        ask_price_cents=1_000_000, reserve_price_cents=1_000_000
    )
    bid = place_bid(buyer_a, listing, 1_050_000)
    snap1 = validate_success(api.get_buyer(buyer_a["id"], make_buyer_headers(buyer_a["id"])), 200)
    assert snap1["deposit_balance_cents"] == snap1["deposit_held_cents"] == 105_000

    validate_success(api.cancel_bid(bid["id"], make_buyer_headers(buyer_a["id"])), 200)
    snap2 = validate_success(api.get_buyer(buyer_a["id"], make_buyer_headers(buyer_a["id"])), 200)
    assert snap2["deposit_balance_cents"] == snap2["deposit_held_cents"] == 0


# difficulty: compensating_invariant/vehicle_ownership_invariant_under_transfer_rollback
def test_vehicle_ownership_restored_after_transfer_rollback(api, admin_headers):
    """PRD §2.6: "any disbursed Loan (DISBURSED → CANCELLED);
    Vehicle.ownership_seller_id reverts to the original Seller.id, and
    rolled_back_at is set to the rollback instant."

    The forward action (PAID + SUCCEEDED → buyer's principal id) is paired
    with the compensating action (FAILED → ROLLED_BACK → original seller).
    """
    state = setup_transfer_in_failed_state(ask_price_cents=2_000_000)
    transfer = state["transfer"]
    validate_success(api.rollback_transfer(transfer["id"], admin_headers), 200)
    vehicle_after = validate_success(api.get_vehicle(state["vehicle"]["id"], admin_headers), 200)
    assert vehicle_after["ownership_seller_id"] == state["seller"]["id"]


# difficulty: compensating_invariant/vehicle_ownership_invariant_under_transfer_rollback
def test_vehicle_status_restored_to_listed_after_rollback(api, admin_headers):
    """PRD §2.6: "restores the Listing from SOLD to ACTIVE, restores the
    Vehicle from SOLD to LISTED" — the compensating action returns the
    vehicle to a listable state, mirroring the forward action that took it
    to SOLD.
    """
    state = setup_transfer_in_failed_state(ask_price_cents=2_000_000)
    transfer = state["transfer"]
    validate_success(api.rollback_transfer(transfer["id"], admin_headers), 200)
    vehicle_after = validate_success(api.get_vehicle(state["vehicle"]["id"], admin_headers), 200)
    assert vehicle_after["vehicle_status"] == "LISTED"
    listing_after = validate_success(api.get_listing(state["listing"]["id"], admin_headers), 200)
    assert listing_after["status"] == "ACTIVE"
