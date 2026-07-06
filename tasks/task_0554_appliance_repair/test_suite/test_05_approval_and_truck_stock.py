"""Estimate approval: truck-stock reservation, boundary, and ownership."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_service_request, assert_truck_stock_item,
    setup_scheduled_request, diagnose_request, setup_approved_request, setup_diagnosed_request,
    get_truck_stock, create_customer, make_customer_headers, TEST_USERS,
)

ADMIN = TEST_USERS["service_admin_headers"]


def _diagnosed_with_required(model, on_hand, required_qty):
    """A DIAGNOSED request whose estimate requires `required_qty` of the single stocked part."""
    ctx = setup_scheduled_request(model=model, quantity_on_hand=on_hand)
    diagnose_request(ctx, labor_tasks=[{"minutes": 40}],
                     required_parts=[{"part_id": ctx["part_id"], "quantity": required_qty}])
    return ctx


# ─── Difficulty: truck_stock_reserve_exact_available_boundary ──────────────
def test_reserve_exactly_available_quantity_succeeds(api):
    """PRD §2.9: "A reservation is permitted only when `quantity_available` is greater than or
    equal to the requested quantity — the boundary is inclusive, so a truck with exactly the
    requested number available may reserve it."

    Design: Difficulty/boundary_precision_check/truck_stock_reserve_exact_available_boundary
    """
    ctx = _diagnosed_with_required("MB10", on_hand=3, required_qty=3)
    # PRD §3.4 covers that approval SUCCEEDS when quantity_available == requested
    # (inclusive boundary). The decision endpoint is /estimates/{id}/decision and PRD
    # does not pin which resource its body echoes, so we assert only that the approve
    # succeeds and the addressed resource reaches APPROVED (both estimate and request
    # transition to APPROVED). assert_service_request() would over-assert the shape.
    res = validate_success(api.decide_estimate(ctx["est_id"], {"decision": "APPROVE"},
                                               make_customer_headers(ctx["cust_id"])), 200)
    assert res["status"] == "APPROVED"


def test_reserve_exact_available_zeroes_out_availability(api):
    """PRD §2.9: "the computed `quantity_available`, which is always `quantity_on_hand` minus
    `quantity_reserved`."
    PRD §3.4: "the system reserves parts — for each required line, adding its `quantity` to the
    technician's `quantity_reserved`".

    Design: Difficulty/boundary_precision_check/truck_stock_reserve_exact_available_boundary
    """
    ctx = _diagnosed_with_required("MB11", on_hand=3, required_qty=3)
    validate_success(api.decide_estimate(ctx["est_id"], {"decision": "APPROVE"},
                                         make_customer_headers(ctx["cust_id"])), 200)
    ts = get_truck_stock(ctx)
    assert_truck_stock_item(ts)
    assert ts["quantity_reserved"] == 3
    assert ts["quantity_available"] == 0


# ─── Corner: insufficient_truck_stock_below_boundary_rejected ──────────────
def test_reserve_above_available_rejected_no_reservation(api):
    """PRD §3.4: "for every line in `required_parts`, the assigned technician's matching
    `TruckStockItem` has `quantity_available` greater than or equal to that line's `quantity`;
    if any part falls short the approval is rejected with `ERR_INSUFFICIENT_TRUCK_STOCK`."

    Design: Corner/cross_cutting/insufficient_truck_stock_below_boundary_rejected
    """
    ctx = _diagnosed_with_required("NG0", on_hand=3, required_qty=4)
    res = api.decide_estimate(ctx["est_id"], {"decision": "APPROVE"},
                              make_customer_headers(ctx["cust_id"]))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_TRUCK_STOCK)
    ts = get_truck_stock(ctx)
    assert ts["quantity_reserved"] == 0, "a rejected approval must not reserve anything"


# ─── Corner: reservation_visible_in_same_request_response (immediate consistency) ──
def test_reservation_immediately_visible_after_approval(api):
    """PRD §3.4: "the system reserves parts — for each required line, adding its `quantity` to
    the technician's `quantity_reserved`".
    PRD §2.9: "the computed `quantity_available`, which is always `quantity_on_hand` minus
    `quantity_reserved`."

    Design: Corner/consistency_model/reservation_visible_in_same_request_response
    """
    ctx = setup_approved_request(model="NH0", quantity_on_hand=5)  # requires part x2 by default
    ts = get_truck_stock(ctx)
    assert ts["quantity_reserved"] == 2
    assert ts["quantity_available"] == 3


# ─── Corner: wrong_customer_approve_returns_not_owner ──────────────────────
def test_non_owning_customer_cannot_approve(api):
    """PRD §3.4: "only the customer who owns the request may do so (`ERR_NOT_OWNER`), and the
    estimate must be `PENDING_APPROVAL` or the decision is rejected with
    `ERR_ESTIMATE_NOT_PENDING`."

    Design: Corner/validations/wrong_customer_approve_returns_not_owner
    """
    ctx = setup_diagnosed_request(model="N90")  # owned by ctx["cust_id"]
    other = create_customer(email="other@example.com")
    res = api.decide_estimate(ctx["est_id"], {"decision": "APPROVE"},
                              make_customer_headers(other["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_OWNER)
