"""Grading dispute cyclic state machine and the depth-3 regrade cascade.

Queue A: non_linear_state_machine/grading_dispute_needs_info_cycle,
         transitive_cascade/dispute_regrade_cascade_depth3.
"""
from test_helpers import (
    validate_success,
    TEST_USERS, make_customer_headers,
    register_customer, create_product, create_inventory_item,
    setup_dispute_under_review, open_order, add_line,
)

GRADER = TEST_USERS["grader_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# Queue A — grading_dispute_needs_info_cycle (>=2 tests)
# ---------------------------------------------------------------------------
def _dispute_after_first_loop(api):
    """Dispute under review, one NEEDS_INFO<->UNDER_REVIEW loop done, then request-info
    again so it sits in NEEDS_INFO awaiting a second provide-info."""
    customer, product, item, dispute = setup_dispute_under_review(
        api, base_price_cents=2500, item_grade="VG", claimed_grade="VG_PLUS")
    validate_success(api.request_info(dispute["id"], GRADER))
    validate_success(api.provide_info(dispute["id"], make_customer_headers(customer["id"])))
    validate_success(api.request_info(dispute["id"], GRADER))
    return customer, dispute


def test_dispute_reenters_under_review_after_second_provide_info(api):
    """PRD §3.8: "While under review, the grader may request more information, moving the
    dispute to NEEDS_INFO; the buyer then provides information, moving it back to
    UNDER_REVIEW. This revision loop between NEEDS_INFO and UNDER_REVIEW may repeat any
    number of times."

    Design: Difficulty/non_linear_state_machine/grading_dispute_needs_info_cycle
    """
    customer, dispute = _dispute_after_first_loop(api)
    data = validate_success(api.provide_info(dispute["id"], make_customer_headers(customer["id"])))
    assert data["status"] == "UNDER_REVIEW", f"second provide-info must re-enter UNDER_REVIEW, got {data['status']}"


def test_dispute_provide_info_returns_to_under_review_first_loop(api):
    """PRD §3.8: "the buyer then provides information, moving it back to UNDER_REVIEW. This
    revision loop between NEEDS_INFO and UNDER_REVIEW may repeat any number of times."

    Design: Difficulty/non_linear_state_machine/grading_dispute_needs_info_cycle
    """
    customer, product, item, dispute = setup_dispute_under_review(
        api, base_price_cents=2500, item_grade="VG", claimed_grade="VG_PLUS")
    validate_success(api.request_info(dispute["id"], GRADER))
    data = validate_success(api.provide_info(dispute["id"], make_customer_headers(customer["id"])))
    assert data["status"] == "UNDER_REVIEW", f"got {data['status']}"


# ---------------------------------------------------------------------------
# Queue A — dispute_regrade_cascade_depth3 (>=2 tests)
# ---------------------------------------------------------------------------
def _open_order_with_disputed_used_item(api):
    """Used VG copy of base-2000 product (lists 1200) on an ONLINE RESERVED order, with an
    OPEN dispute moved to UNDER_REVIEW. Returns (buyer, item, order, line, dispute)."""
    buyer = register_customer(api, full_name="Cascade Buyer")
    product = create_product(api, artist="The Beatles", title="Abbey Road", format="VINYL",
                             base_price_cents=2000)
    item = create_inventory_item(api, product_id=product["id"], is_used=True, condition_grade="VG")
    order = open_order(api, customer=buyer, channel="ONLINE")
    line = add_line(api, order=order, customer=buyer, item=item)
    hdr = make_customer_headers(buyer["id"])
    dispute = validate_success(api.create_dispute(
        {"inventory_item_id": item["id"], "customer_id": buyer["id"], "claimed_grade": "G"}, hdr),
        expected_status=201)
    validate_success(api.start_review(dispute["id"], GRADER))
    return buyer, item, order, line, dispute


def test_regrade_cascade_updates_item_grade_and_price(api):
    """PRD §3.8: "First, the disputed InventoryItem's condition_grade is set to the
    resolution_grade. Second, that copy's list_price_cents is recomputed under the item
    pricing rule of §3.1 at the new grade." PRD §2.5: "G by 0.40".

    Design: Difficulty/transitive_cascade/dispute_regrade_cascade_depth3
    """
    buyer, item, order, line, dispute = _open_order_with_disputed_used_item(api)
    hdr = make_customer_headers(buyer["id"])
    validate_success(api.resolve_regrade(dispute["id"], {"resolution_grade": "G"}, GRADER))
    item_after = validate_success(api.get_inventory_item(item["id"], hdr))
    assert item_after["condition_grade"] == "G", f"got {item_after['condition_grade']}"
    # base 2000 * 0.40 = 800.
    assert item_after["list_price_cents"] == 800, f"got {item_after['list_price_cents']}"


def test_regrade_cascade_resyncs_order_line_and_totals(api):
    """PRD §3.8: "Third, if that copy sits on an OrderLine whose order has a
    fulfillment_status of PENDING or RESERVED ... the line's unit_price_cents is resynced
    to the copy's new price and the order's subtotal_cents, discount_cents, shipping_cents,
    and total_cents are recomputed under the order-total rule of §3.2."

    Design: Difficulty/transitive_cascade/dispute_regrade_cascade_depth3
    """
    buyer, item, order, line, dispute = _open_order_with_disputed_used_item(api)
    hdr = make_customer_headers(buyer["id"])
    validate_success(api.resolve_regrade(dispute["id"], {"resolution_grade": "G"}, GRADER))
    line_after = validate_success(api.get_order_line(line["id"], hdr))
    assert line_after["unit_price_cents"] == 800, f"line resync must be 800, got {line_after['unit_price_cents']}"
    order_after = validate_success(api.get_order(order["id"], hdr))
    assert order_after["subtotal_cents"] == 800, f"got {order_after['subtotal_cents']}"
    # used copy => no discount; ONLINE subtotal 800<5000 => ship 599; total 1399.
    assert order_after["total_cents"] == 1399, f"got {order_after['total_cents']}"
