"""Tests for PRD §3.9 — Dispute mediation: filing eligibility, multi-stage
mediation, cyclic SUBMITTED↔EVIDENCE_REVIEW with round_count cap, and the
four resolutions (REFUND_FULL, REFUND_PARTIAL, COMPENSATE_SELLER, NO_ACTION)
with their cents-precise refund calculations.
"""

import pytest

from test_helpers import (
    api_client,
    assert_dispute_case,
    dispute_payload,
    file_dispute,
    make_buyer_headers,
    register_buyer,
    setup_completed_purchase_order,
    setup_dispute_at_round,
    setup_paid_purchase_order,
    validate_error,
    validate_success,
)


# ──────────────────────────────────────────────────────────
# §3.9 Dispute filing eligibility
# ──────────────────────────────────────────────────────────


def test_dispute_on_pending_payment_purchase_order_rejected(api):
    """PRD §3.9: "A buyer or seller may file a DisputeCase against a
    PurchaseOrder, but only when the order's status is COMPLETED or
    AWAITING_TRANSFER; filing against a pre-payment order is rejected with
    ERR_DISPUTE_NOT_ELIGIBLE."
    """
    from test_helpers import (
        create_purchase_order_payload,
        setup_holding_reservation,
    )

    seller, vehicle, listing, buyer, _ = setup_holding_reservation(ask_price_cents=2_000_000)
    payload = create_purchase_order_payload(listing["id"])
    payload["package_code"] = "STANDARD"
    po = validate_success(
        api.create_purchase_order(payload, make_buyer_headers(buyer["id"])), 201
    )
    res = api.create_dispute(
        po["id"],
        dispute_payload(complainant_role="BUYER"),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, "ERR_DISPUTE_NOT_ELIGIBLE")


def test_dispute_on_awaiting_transfer_purchase_order_succeeds(api):
    """PRD §3.9: "the order's status is COMPLETED or AWAITING_TRANSFER".
    AWAITING_TRANSFER must be eligible.
    """
    state = setup_paid_purchase_order(ask_price_cents=2_000_000)
    dispute = file_dispute(state)
    assert_dispute_case(dispute)
    assert dispute["stage"] == "SUBMITTED"
    assert dispute["round_count"] == 0


# ──────────────────────────────────────────────────────────
# §3.9 round_count cap
# ──────────────────────────────────────────────────────────


def test_start_review_increments_round_count(api, admin_headers):
    """PRD §3.9: "A platform admin starts review by transitioning the case
    from SUBMITTED to EVIDENCE_REVIEW, which increments round_count by one."
    """
    state = setup_completed_purchase_order(ask_price_cents=2_000_000)
    dispute = file_dispute(state)
    started = validate_success(api.start_review_dispute(dispute["id"], admin_headers), 200)
    assert started["stage"] == "EVIDENCE_REVIEW"
    assert started["round_count"] == 1


def test_request_more_evidence_at_round_three_rejected(api, admin_headers):
    """PRD §3.9: "this cyclic shape is capped — round_count may not exceed
    the maximum mediation rounds of three, and any start-review or
    request-more-evidence step that would push it beyond is rejected with
    ERR_DISPUTE_ROUNDS_EXHAUSTED."
    """
    state = setup_completed_purchase_order(ask_price_cents=2_000_000)
    # Drive the dispute through to round_count=3.
    dispute = setup_dispute_at_round(state, round_count=3)
    assert dispute["round_count"] == 3
    assert dispute["stage"] == "EVIDENCE_REVIEW"
    res = api.request_more_evidence(dispute["id"], admin_headers)
    validate_error(res, "ERR_DISPUTE_ROUNDS_EXHAUSTED")


# ──────────────────────────────────────────────────────────
# §3.9 Resolutions — REFUND_FULL
# ──────────────────────────────────────────────────────────


def test_refund_full_sets_refund_amount_to_agreed_price_and_voids_warranty(api, admin_headers):
    """PRD §3.9: "If the resolution is REFUND_FULL, refund_amount_cents
    equals the order's agreed_price_cents, and the order is cascaded into
    REFUNDED with the full transfer-rollback compensation chain (listing,
    vehicle, warranty, loan all reverted as in §2.6) and the warranty is
    moved from ACTIVE to VOIDED."
    """
    state = setup_completed_purchase_order(ask_price_cents=5_000_000)
    dispute = file_dispute(state)
    validate_success(api.start_review_dispute(dispute["id"], admin_headers), 200)
    proposed = validate_success(
        api.propose_resolution(
            dispute["id"], {"resolution": "REFUND_FULL"}, admin_headers
        ),
        200,
    )
    assert proposed["resolution"] == "REFUND_FULL"
    closed = validate_success(api.execute_dispute(dispute["id"], admin_headers), 200)
    assert closed["stage"] == "CLOSED"
    assert closed["refund_amount_cents"] == 5_000_000

    po_after = validate_success(
        api.get_purchase_order(state["purchase_order"]["id"], admin_headers), 200
    )
    assert po_after["status"] == "REFUNDED"
    if state.get("warranty"):
        warranty_after = validate_success(
            api.get_warranty(state["warranty"]["id"], admin_headers), 200
        )
        assert warranty_after["status"] == "VOIDED"


# ──────────────────────────────────────────────────────────
# §3.9 Resolutions — REFUND_PARTIAL (10% no third-party, 30% with)
# ──────────────────────────────────────────────────────────


def test_refund_partial_without_third_party_uses_ten_percent(api, admin_headers):
    """PRD §3.9: "If the resolution is REFUND_PARTIAL, the refund is computed
    as the order's agreed_price_cents multiplied by a base percentage and
    rounded half-up to integer cents, where the base percentage is ten
    percent if no third_party_report_url was filed".

    agreed=5_000_000 → refund = 5_000_000 * 0.10 = 500_000.
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


def test_refund_partial_with_third_party_uses_thirty_percent(api, admin_headers):
    """PRD §3.9: "thirty percent if one was".

    agreed=5_000_000, third-party report present → refund = 1_500_000.
    """
    state = setup_completed_purchase_order(ask_price_cents=5_000_000)
    dispute = file_dispute(state)
    validate_success(api.start_review_dispute(dispute["id"], admin_headers), 200)
    validate_success(api.request_third_party(dispute["id"], admin_headers), 200)
    validate_success(
        api.submit_third_party_report(
            dispute["id"],
            {"third_party_report_url": "https://inspections.example.com/report-123.pdf"},
            admin_headers,
        ),
        200,
    )
    # After submit_third_party_report, the dispute is in RESOLUTION_PROPOSED;
    # PRD §3.9 says propose-resolution must set the resolution. Implementations
    # vary on whether resolution is set before execute or via a propose step
    # while in RESOLUTION_PROPOSED — but the execute body should accept it.
    # Try both: if propose-resolution on RESOLUTION_PROPOSED is rejected, set
    # via execute body.
    propose_res = api.propose_resolution(
        dispute["id"], {"resolution": "REFUND_PARTIAL"}, admin_headers
    )
    if propose_res.status_code >= 400:
        # Set the resolution via execute body — PRD §3.9: "A dispute that the
        # admin starts but does not yet have an executable resolution must
        # have its resolution set before the execute step".
        closed = validate_success(
            api.execute_dispute(
                dispute["id"], admin_headers, payload={"resolution": "REFUND_PARTIAL"}
            ),
            200,
        )
    else:
        closed = validate_success(api.execute_dispute(dispute["id"], admin_headers), 200)
    assert closed["refund_amount_cents"] == 1_500_000


def test_compensate_seller_uses_five_percent_of_agreed_price(api, admin_headers):
    """PRD §3.9: "If the resolution is COMPENSATE_SELLER, the buyer pays the
    seller five percent of the order's agreed_price_cents rounded half-up".

    agreed=5_000_000 → 250_000.
    """
    state = setup_completed_purchase_order(ask_price_cents=5_000_000)
    dispute = file_dispute(state)
    validate_success(api.start_review_dispute(dispute["id"], admin_headers), 200)
    validate_success(
        api.propose_resolution(
            dispute["id"], {"resolution": "COMPENSATE_SELLER"}, admin_headers
        ),
        200,
    )
    closed = validate_success(api.execute_dispute(dispute["id"], admin_headers), 200)
    assert closed["refund_amount_cents"] == 250_000


def test_no_action_resolution_yields_zero_refund(api, admin_headers):
    """PRD §3.9: "If the resolution is NO_ACTION, refund_amount_cents is zero
    and no monetary movement occurs."
    """
    state = setup_completed_purchase_order(ask_price_cents=5_000_000)
    dispute = file_dispute(state)
    validate_success(api.start_review_dispute(dispute["id"], admin_headers), 200)
    validate_success(
        api.propose_resolution(
            dispute["id"], {"resolution": "NO_ACTION"}, admin_headers
        ),
        200,
    )
    closed = validate_success(api.execute_dispute(dispute["id"], admin_headers), 200)
    assert closed["refund_amount_cents"] == 0
