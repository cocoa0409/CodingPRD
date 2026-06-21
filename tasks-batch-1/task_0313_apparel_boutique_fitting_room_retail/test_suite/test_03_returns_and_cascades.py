"""Return approval/rejection forks, multi-level cascades, and refund-void compensation.

Queue A (Difficulty): non_linear_state_machine (return fork), transitive_cascade
(return depth-4), compensating_invariant (return void conserves credit + points).
Queue B (Corner): validations (exchange unavailable).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    create_boutique, create_customer, create_style, create_variant,
    create_completed_order, setup_completed_order_scenario,
    file_refund_return, file_exchange_return, setup_approved_refund_return,
)

ASSOCIATE = TEST_USERS["store_associate_headers"]
MANAGER = TEST_USERS["store_manager_headers"]


# ─── Queue A: non_linear_state_machine (return fork) ──────────────────────

def test_return_reject_grants_nothing_and_leaves_line_sold(api):
    """PRD §3.7: "Rejecting a return (REQUESTED -> REJECTED) is a StoreManager action
    that makes no inventory or ledger change."

    A REFUND return rejected leaves refund_cents 0, store credit 0, and the line SOLD.

    Design: Difficulty/non_linear_state_machine/return_request_fork_approve_vs_reject_divergent_effects
    """
    bq, cu, style, variant, order, line = setup_completed_order_scenario(
        tax_rate_bps=0, list_price_cents=5000, return_window_days=30)
    rr = file_refund_return(order["id"], line["id"])

    rejected = validate_success(api.reject_return(rr["id"], MANAGER), 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["refund_cents"] == 0

    customer_after = get_success_data(api.get_customer(cu["id"], ASSOCIATE))
    assert customer_after["store_credit_cents"] == 0

    line_after = get_success_data(api.get_order_line(line["id"], ASSOCIATE))
    assert line_after["status"] == "SOLD"


def test_return_approve_grants_refund_credit(api):
    """PRD §3.7: "For a REFUND, the system grants refund_cents equal to the returned
    line's line_total_cents into the customer's store_credit_cents and refreshes the
    boutique's store_credit_outstanding_cents."
    PRD §3.7: "At the first level the order line's status is set — RETURNED for a
    refund or EXCHANGED for an exchange."

    Approving a REFUND on a 5000 line grants 5000 store credit (the divergent branch
    from reject), with the line set RETURNED.

    Design: Difficulty/non_linear_state_machine/return_request_fork_approve_vs_reject_divergent_effects
    """
    bq, cu, style, variant, order, line = setup_completed_order_scenario(
        tax_rate_bps=0, list_price_cents=5000, return_window_days=30)
    rr = file_refund_return(order["id"], line["id"])

    approved = validate_success(api.approve_return(rr["id"], ASSOCIATE), 200)
    assert approved["status"] == "APPROVED"
    assert approved["refund_cents"] == 5000

    customer_after = get_success_data(api.get_customer(cu["id"], ASSOCIATE))
    assert customer_after["store_credit_cents"] == 5000

    line_after = get_success_data(api.get_order_line(line["id"], ASSOCIATE))
    assert line_after["status"] == "RETURNED"


# ─── Queue A: transitive_cascade (return depth-4) ─────────────────────────

def test_return_approve_cascades_line_to_sku_to_style(api):
    """PRD §3.7: "At the first level the order line's status is set — RETURNED for a
    refund or EXCHANGED for an exchange. That line-status change, at the second level,
    increments the line's variant on_hand by the line qty (the unit is restocked) and
    recomputes available; at the third level the variant's change bubbles up to
    recompute the parent style's total_available."

    A captured sale dropped the variant to on_hand 4 / available 4; approving the
    REFUND restocks to on_hand 5, available 5, total_available 5 across all three hops.

    Design: Difficulty/transitive_cascade/return_approve_cascade_depth4_line_sku_style
    """
    bq, cu, style, variant, order, line = setup_completed_order_scenario(
        tax_rate_bps=0, list_price_cents=5000, return_window_days=30)
    variant_before = get_success_data(api.get_sku_variant(variant["id"], ASSOCIATE))
    assert variant_before["on_hand"] == 4 and variant_before["available"] == 4

    rr = file_refund_return(order["id"], line["id"])
    validate_success(api.approve_return(rr["id"], ASSOCIATE), 200)

    line_after = get_success_data(api.get_order_line(line["id"], ASSOCIATE))
    assert line_after["status"] == "RETURNED"

    variant_after = get_success_data(api.get_sku_variant(variant["id"], ASSOCIATE))
    assert variant_after["on_hand"] == 5
    assert variant_after["available"] == 5

    style_after = get_success_data(api.get_style(style["id"], ASSOCIATE))
    assert style_after["total_available"] == 5


def test_return_approve_reverses_loyalty_points(api):
    """PRD §3.7: "In both resolutions the system reverses the loyalty the line earned:
    points_reversed equals the points minted for that line ... those points are removed
    from the customer's loyalty_points and the line's captured spend is removed from
    captured_spend_cents".
    PRD §3.7: "if no order line of the order remains in SOLD status after the cascade,
    the system transitions the order's payment_status from CAPTURED to REFUNDED,
    reversing any still-outstanding points back to the pre-order baseline".

    A single-line order earning 54 points is fully returned; loyalty_points return to
    0 and the order's payment_status becomes REFUNDED.

    Design: Difficulty/transitive_cascade/return_approve_cascade_depth4_line_sku_style
    """
    bq, cu, style, variant, order, line = setup_completed_order_scenario(
        tax_rate_bps=875, list_price_cents=5000, return_window_days=30)
    customer_before = get_success_data(api.get_customer(cu["id"], ASSOCIATE))
    assert customer_before["loyalty_points"] == 54

    rr = file_refund_return(order["id"], line["id"])
    validate_success(api.approve_return(rr["id"], ASSOCIATE), 200)

    customer_after = get_success_data(api.get_customer(cu["id"], ASSOCIATE))
    assert customer_after["loyalty_points"] == 0

    order_after = get_success_data(api.get_sales_order(order["id"], ASSOCIATE))
    assert order_after["payment_status"] == "REFUNDED"


# ─── Queue A: compensating_invariant (return void) ────────────────────────

def test_void_refund_return_restores_credit_and_points(api):
    """PRD §3.7: "Voiding a return (APPROVED -> VOIDED) is also a StoreManager action,
    permitted only when the return's resolution is REFUND ... and it fully compensates
    the approval: the order line's status is set back to SOLD, the variant's on_hand is
    decremented by qty ... the granted refund_cents is clawed back from the customer's
    store_credit_cents ... and the previously reversed points_reversed are re-minted
    onto loyalty_points and captured_spend_cents with the tier recomputed."

    A 5000 line earning 54 points: approve grants 5000 credit and reverses 54 points;
    voiding claws the credit back to 0, re-mints 54 points, sets the line SOLD, and the
    restock is undone (on_hand back to 4).

    Design: Difficulty/compensating_invariant/return_void_conserves_store_credit_and_points
    """
    bq, cu, style, variant, order, line, approved = setup_approved_refund_return(
        tax_rate_bps=875, list_price_cents=5000, return_window_days=30)
    assert approved["status"] == "APPROVED"

    customer_after_approve = get_success_data(api.get_customer(cu["id"], ASSOCIATE))
    assert customer_after_approve["store_credit_cents"] == 5000
    assert customer_after_approve["loyalty_points"] == 0

    voided = validate_success(api.void_return(approved["id"], MANAGER), 200)
    assert voided["status"] == "VOIDED"

    customer_after_void = get_success_data(api.get_customer(cu["id"], ASSOCIATE))
    assert customer_after_void["store_credit_cents"] == 0
    assert customer_after_void["loyalty_points"] == 54

    line_after = get_success_data(api.get_order_line(line["id"], ASSOCIATE))
    assert line_after["status"] == "SOLD"

    variant_after = get_success_data(api.get_sku_variant(variant["id"], ASSOCIATE))
    assert variant_after["on_hand"] == 4


def test_void_refund_return_restocks_back_out(api):
    """PRD §3.7: "the variant's on_hand is decremented by qty with available recomputed
    and total_available bubbled up".
    PRD §3.7: "the order line's status is set back to SOLD".

    After approve restocked the variant to on_hand 5, voiding decrements on_hand back to
    4 and the line returns to SOLD — physical-unit conservation across approve+void.

    Design: Difficulty/compensating_invariant/return_void_conserves_store_credit_and_points
    """
    bq, cu, style, variant, order, line, approved = setup_approved_refund_return(
        tax_rate_bps=875, list_price_cents=5000, return_window_days=30)
    variant_after_approve = get_success_data(api.get_sku_variant(variant["id"], ASSOCIATE))
    assert variant_after_approve["on_hand"] == 5

    validate_success(api.void_return(approved["id"], MANAGER), 200)

    variant_after_void = get_success_data(api.get_sku_variant(variant["id"], ASSOCIATE))
    assert variant_after_void["on_hand"] == 4
    assert variant_after_void["available"] == 4

    line_after = get_success_data(api.get_order_line(line["id"], ASSOCIATE))
    assert line_after["status"] == "SOLD"


# ─── Queue B: validations (exchange unavailable) ──────────────────────────

def test_exchange_return_with_unavailable_variant_rejected(api):
    """PRD §3.7: "For an exchange resolution there is a further requirement, evaluated
    as its own business check: exchange_sku_variant_id must be present and the named
    variant must have available of at least 1, or approval is rejected with
    ERR_EXCHANGE_UNAVAILABLE (HTTP 409)."

    Approving an EXCHANGE return whose target variant has available 0 returns
    ERR_EXCHANGE_UNAVAILABLE.

    Design: Corner/validations/exchange_return_missing_variant_rejected
    """
    bq = create_boutique(tax_rate_bps=0, return_window_days=30)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="TOPS", season="SPRING")
    variant = create_variant(style["id"], size="M", color="Blue", on_hand=5)
    empty_variant = create_variant(style["id"], size="L", color="Blue", on_hand=0)

    order, line = create_completed_order(cu["id"], variant["id"], qty=1)
    rr = file_exchange_return(order["id"], line["id"], empty_variant["id"])

    res = api.approve_return(rr["id"], ASSOCIATE)
    validate_error(res, ApiErrorId.ERR_EXCHANGE_UNAVAILABLE.value)
