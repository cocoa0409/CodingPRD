"""Order/Shipment lifecycle: parallel status dimensions, full pick/load/POD chain,
and the precondition guards along the way.

Covers difficulty non_linear_state_machine (order parallel dimensions) and the corner
state_machines instances.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_catalog, create_submitted_order, create_approved_order, create_delivered_order,
    get_customer_version, approve_credit_payload, pod_payload, shipment_for_order,
    TEST_USERS,
)

CREDIT = TEST_USERS["credit_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]
WAREHOUSE = TEST_USERS["warehouse_op_headers"]


def test_approve_credit_advances_credit_status_only(api):
    """PRD §3.4: "it leaves `fulfillment_status` at `SUBMITTED` while moving
    `credit_status` from `PENDING` toward `APPROVED`."

    The Order carries two independent state axes: approve-credit moves credit_status to
    APPROVED while fulfillment_status stays SUBMITTED.

    Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_and_credit_dimensions
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=12, credit_limit_cents=100000)
    order, _ = create_submitted_order(cat["customer"]["id"], cat["product"]["id"],
                                      lines=[(cat["product"]["id"], "CASE", 1)])
    cust_v = get_customer_version(cat["customer"]["id"])
    approved = validate_success(
        api.approve_credit(order["id"], approve_credit_payload(cust_v), CREDIT), 200)
    assert approved["credit_status"] == "APPROVED"
    assert approved["fulfillment_status"] == "SUBMITTED"


def test_start_pick_advances_fulfillment_leaving_credit_approved(api):
    """PRD §3.6: "Starting the pick advances the order's `fulfillment_status` from
    `SUBMITTED` to `PICKING` and creates a `Shipment` for the order."

    Second test of the parallel dimensions: after start-pick, fulfillment_status is PICKING
    while credit_status remains APPROVED — the two axes evolve independently.

    Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_and_credit_dimensions
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=24, credit_limit_cents=100000)
    order, _ = create_approved_order(cat["customer"]["id"], cat["product"]["id"],
                                     lines=[(cat["product"]["id"], "CASE", 2)])
    picked = validate_success(api.start_pick(order["id"], WAREHOUSE), 200)
    assert picked["fulfillment_status"] == "PICKING"
    assert picked["credit_status"] == "APPROVED"


def test_full_lifecycle_to_delivered_settles_and_consumes_stock(api):
    """PRD §3.6: "the shipment's `status` becomes `DELIVERED` and the order's
    `fulfillment_status` becomes `DELIVERED`, with the order's `settled` flag flipped to
    true."
    PRD §3.6: "for each allocated lot, both its `on_hand_splits` and its `reserved_splits`
    are decremented by the line's `allocated_splits` — the reserved stock is converted into
    shipped stock."

    A start-pick -> load -> POD chain drives a CASE-2 order (lot 24) to DELIVERED, settled
    true, consuming the lot (on_hand 24->0, reserved ->0).

    Design: Corner/state_machines/order_full_lifecycle_to_delivered_settles
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=24, credit_limit_cents=100000)
    lot = cat["lot"]
    order, lines, ship = create_delivered_order(
        cat["customer"]["id"], cat["product"]["id"],
        lines=[(cat["product"]["id"], "CASE", 2)], pod_signature="Sig")
    assert order["fulfillment_status"] == "DELIVERED"
    assert order["settled"] is True

    lot_after = validate_success(api.get_inventory_lot(lot["id"], SALES), 200)
    assert lot_after["on_hand_splits"] == 0
    assert lot_after["reserved_splits"] == 0


def test_start_pick_before_credit_approved_rejected(api):
    """PRD §3.6: "Starting the pick requires that `credit_status` is `APPROVED`, or it is
    rejected with `ERR_CREDIT_NOT_APPROVED`."

    start-pick on a SUBMITTED order whose credit_status is still PENDING is rejected
    ERR_CREDIT_NOT_APPROVED (409).

    Design: Corner/state_machines/start_pick_before_credit_approved_returns_credit_not_approved
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=24, credit_limit_cents=100000)
    order, _ = create_submitted_order(cat["customer"]["id"], cat["product"]["id"],
                                      lines=[(cat["product"]["id"], "CASE", 2)])
    res = api.start_pick(order["id"], WAREHOUSE)
    validate_error(res, "ERR_CREDIT_NOT_APPROVED")


def test_cancel_delivered_order_rejected_terminal(api):
    """PRD §3.6: "A `SUBMITTED` order may also be cancelled — this requires the order to
    actually be in `SUBMITTED`, else `ERR_INVALID_STATE`."
    PRD §3.6: "The order's `fulfillment_status` becomes `CANCELLED`, which together with
    `DELIVERED` is a terminal fulfillment state."

    Cancelling a DELIVERED (terminal) order is rejected ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_delivered_order_invalid_from_terminal_rejected
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=24, credit_limit_cents=100000)
    order, lines, ship = create_delivered_order(
        cat["customer"]["id"], cat["product"]["id"],
        lines=[(cat["product"]["id"], "CASE", 2)], pod_signature="Sig")
    res = api.cancel_order(order["id"], SALES)
    validate_error(res, "ERR_INVALID_STATE")


def test_pod_without_signature_rejected(api):
    """PRD §3.6: "It requires the shipment to be in `LOADED`, or it is rejected with
    `ERR_INVALID_STATE`, and a non-empty `pod_signature`, or it is rejected with
    `ERR_POD_SIGNATURE_REQUIRED`."

    POD on a LOADED shipment with an empty pod_signature is rejected
    ERR_POD_SIGNATURE_REQUIRED (422).

    Design: Corner/state_machines/pod_without_signature_returns_signature_required
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=24, credit_limit_cents=100000)
    order, _ = create_approved_order(cat["customer"]["id"], cat["product"]["id"],
                                     lines=[(cat["product"]["id"], "CASE", 2)])
    validate_success(api.start_pick(order["id"], WAREHOUSE), 200)
    ship = shipment_for_order(order["id"])
    validate_success(api.load_shipment(ship["id"], WAREHOUSE), 200)

    res = api.pod_shipment(ship["id"], pod_payload(""), WAREHOUSE)
    validate_error(res, "ERR_POD_SIGNATURE_REQUIRED")


def test_start_pick_with_all_lines_shorted_rejected(api):
    """PRD §3.6: "that at least one `OrderLine` is in `ALLOCATED` status, or it is rejected
    with `ERR_NOTHING_TO_PICK`."
    PRD §3.4: "A line whose `allocated_splits` equals its full needed quantity ends with
    `line_status` of `ALLOCATED`; otherwise it ends `SHORTED`."

    An approved order whose only line fully SHORTED (no stock, no substitute) has no
    ALLOCATED line; start-pick is rejected ERR_NOTHING_TO_PICK (409).

    Design: Corner/state_machines/nothing_to_pick_when_all_lines_shorted
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        credit_limit_cents=100000, stock=False)
    order, lines = create_submitted_order(cat["customer"]["id"], cat["product"]["id"],
                                          lines=[(cat["product"]["id"], "CASE", 1)])
    line = lines[0]
    cust_v = get_customer_version(cat["customer"]["id"])
    validate_success(api.approve_credit(order["id"], approve_credit_payload(cust_v), CREDIT), 200)

    line_after = validate_success(api.get_order_line(line["id"], SALES), 200)
    assert line_after["line_status"] == "SHORTED"
    assert line_after["short_splits"] == 12

    res = api.start_pick(order["id"], WAREHOUSE)
    validate_error(res, "ERR_NOTHING_TO_PICK")
