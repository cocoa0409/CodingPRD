"""Purchase-order sourcing: blank-cost variants, supplier capacity, reservation ledger."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_purchase_order_payload, reorder_payload,
    setup_issued_po, setup_confirmed_with_po, setup_confirmed_order,
    setup_catalog_customer_order, setup_supplier_capacity_near_limit,
)

AM = TEST_USERS["account_manager_headers"]
PM = TEST_USERS["production_manager_headers"]


# ---- queue A: estimated vs actual blank cost -----------------------------

def test_estimated_blank_cost_computed_at_issue(api):
    """PRD 3.4: "On a successful issue, the `estimated_blank_cost_cents` is computed
    as `ordered_blank_qty` multiplied by the supplier's `blank_unit_cost_cents`, and
    the supplier's `reserved_blank_qty` is increased by `ordered_blank_qty`."

    Design: Difficulty/dual_variant_calc/blank_estimated_vs_actual_cost
    """
    ctx = setup_issued_po(ordered_blank_qty=210)
    po = validate_success(api.get_purchase_order(ctx["po_id"], AM))
    assert po["estimated_blank_cost_cents"] == 31500, f"210*150, got {po['estimated_blank_cost_cents']}"


def test_actual_blank_cost_diverges_from_estimate_at_receive(api):
    """PRD 3.4: "On receipt the `actual_blank_cost_cents` is computed as
    `received_blank_qty` multiplied by the supplier's `blank_unit_cost_cents` (this
    differs from the estimate whenever the supplier under- or over-ships), and the
    supplier's `reserved_blank_qty` is decreased by `ordered_blank_qty`, releasing the
    reservation."

    Design: Difficulty/dual_variant_calc/blank_estimated_vs_actual_cost
    """
    ctx = setup_issued_po(ordered_blank_qty=210)
    validate_success(api.receive_po(ctx["po_id"], {"received_blank_qty": 205}, PM))
    po = validate_success(api.get_purchase_order(ctx["po_id"], AM))
    assert po["estimated_blank_cost_cents"] == 31500
    assert po["actual_blank_cost_cents"] == 30750, f"205*150, got {po['actual_blank_cost_cents']}"
    assert po["actual_blank_cost_cents"] != po["estimated_blank_cost_cents"]


# ---- queue A: aggregate supplier capacity (interval stabbing) ------------

def test_supplier_capacity_exceeded_on_overlapping_issue(api):
    """PRD 3.4: "the peak concurrent load is the maximum over those instants of the
    new order's `ordered_blank_qty` plus the sum of `ordered_blank_qty` of all
    already-`ISSUED` purchase orders on the same supplier whose own windows contain
    that instant. If that peak exceeds the supplier's `concurrent_capacity_units`, the
    issue is rejected with `ERR_SUPPLIER_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/supplier_capacity_aggregate_overlap
    """
    ctx = setup_supplier_capacity_near_limit()
    resp = api.issue_po(ctx["po2_id"], AM)
    validate_error(resp, ApiErrorId.ERR_SUPPLIER_CAPACITY_EXCEEDED)


def test_supplier_capacity_rejection_leaves_po_draft_and_reservation_unchanged(api):
    """PRD 2.11: "The counter starts at 0 when the supplier is created and is
    maintained as an invariant — it rises when a purchase order is issued and falls
    when that order is received or cancelled."
    PRD 3.4: "Issuing a purchase order advances it from `DRAFT` to `ISSUED`; a purchase
    order not in `DRAFT` at issue time yields `ERR_PO_INVALID_STATE`."

    Design: Difficulty/resource_temporal_overlap/supplier_capacity_aggregate_overlap
    """
    ctx = setup_supplier_capacity_near_limit()
    api.issue_po(ctx["po2_id"], AM)
    po2 = validate_success(api.get_purchase_order(ctx["po2_id"], AM))
    supplier = validate_success(api.get_supplier(ctx["supplier_id"], AM))
    assert po2["status"] == "DRAFT"
    assert supplier["reserved_blank_qty"] == 300, "only PO1's 300 remains reserved"


# ---- queue A: issue/cancel conserves supplier blanks ---------------------

def test_po_cancel_releases_supplier_reservation(api):
    """PRD 3.4: "When the cancelled purchase order had been `ISSUED`, the supplier's
    `reserved_blank_qty` is decreased by `ordered_blank_qty` as a compensating release."

    Design: Difficulty/compensating_invariant/po_issue_cancel_conserves_supplier_blanks
    """
    ctx = setup_issued_po(ordered_blank_qty=210)
    validate_success(api.cancel_po(ctx["po_id"], AM))
    supplier = validate_success(api.get_supplier(ctx["supplier_id"], AM))
    assert supplier["reserved_blank_qty"] == 0, "issue (+210) then cancel (-210) nets to 0"


def test_po_cancel_moves_po_to_cancelled(api):
    """PRD 3.4: "Cancelling a purchase order is permitted while it is in `DRAFT` or
    `ISSUED`; any other state yields `ERR_PO_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/po_issue_cancel_conserves_supplier_blanks
    """
    ctx = setup_issued_po(ordered_blank_qty=210)
    validate_success(api.cancel_po(ctx["po_id"], AM))
    po = validate_success(api.get_purchase_order(ctx["po_id"], AM))
    assert po["status"] == "CANCELLED"


# ---- corner: duplicate PO for a line -------------------------------------

def test_duplicate_purchase_order_for_line_rejected(api):
    """PRD 3.4: "At most one active (non-cancelled) purchase order may exist for a
    line; a second attempt is rejected with `ERR_PO_ALREADY_EXISTS`."

    Design: Corner/cross_cutting_complexity_layers/duplicate_purchase_order_for_line_returns_error
    """
    ctx = setup_confirmed_with_po(ordered_blank_qty=210)
    resp = api.create_purchase_order(
        create_purchase_order_payload(ctx["line_id"], ctx["supplier_id"], ordered_blank_qty=210),
        AM)
    validate_error(resp, ApiErrorId.ERR_PO_ALREADY_EXISTS)


# ---- corner: invalid production window ------------------------------------

def test_purchase_order_invalid_time_window_rejected(api):
    """PRD 3.4: "A window whose `production_end` is not strictly after its
    `production_start` is rejected with `ERR_INVALID_TIME_WINDOW`."

    Design: Corner/validations/schedule_invalid_time_window_returns_error
    """
    ctx = setup_confirmed_order()
    resp = api.create_purchase_order(
        create_purchase_order_payload(
            ctx["line_id"], ctx["supplier_id"],
            production_start="2026-05-08T00:00:00Z",
            production_end="2026-05-05T00:00:00Z"),
        AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW)


# ---- corner: reorder from non-delivered source ---------------------------

def test_reorder_from_non_delivered_source_rejected(api):
    """PRD 3.9: "The source order must be in `DELIVERED`, else the reorder is rejected
    with `ERR_REORDER_SOURCE_NOT_DELIVERED`."

    Design: Corner/cross_cutting_complexity_layers/reorder_from_non_delivered_source_returns_error
    """
    ctx = setup_catalog_customer_order()
    resp = api.reorder(ctx["order_id"], reorder_payload(in_hands_date="2026-06-20T00:00:00Z"),
                       ctx["cust_headers"])
    validate_error(resp, ApiErrorId.ERR_REORDER_SOURCE_NOT_DELIVERED)
