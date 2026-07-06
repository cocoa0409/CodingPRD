"""Consignment dual-variant payout, slot overlap/inactive rules.

Queue A: dual_variant_calc/consignment_estimated_vs_actual_payout,
         resource_temporal_overlap/display_slot_buffered_closed_interval_overlap.
Queue B: slot_inactive_activation_rejected.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_customer_headers,
    register_customer, create_product,
    create_display_slot, create_consignment, setup_active_consignment,
    get_consignment_item, open_order, add_line,
)

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["store_clerk_headers"]


# ---------------------------------------------------------------------------
# Queue A — consignment_estimated_vs_actual_payout (>=2 tests)
# ---------------------------------------------------------------------------
def _sold_marked_down_consignment(api):
    """Active consignment listed 10000 (est payout pinned), marked down to 8000,
    then sold via an IN_STORE buyer order that is fulfilled. Returns (consignor, cons)."""
    consignor, product, slot, cons, item = setup_active_consignment(
        api, list_price_cents=10000, condition_grade="VG_PLUS", base_price_cents=3000)
    validate_success(api.markdown_consignment(cons["id"], {"new_list_price_cents": 8000}, MANAGER))
    item = get_consignment_item(api, consignment=cons)
    buyer = register_customer(api, full_name="Buyer")
    order = open_order(api, customer=buyer, channel="IN_STORE")
    add_line(api, order=order, customer=buyer, item=item)
    hdr = make_customer_headers(buyer["id"])
    validate_success(api.authorize_payment(order["id"], hdr))
    validate_success(api.capture_payment(order["id"], {}, CLERK))
    validate_success(api.fulfill_order(order["id"], CLERK))
    return consignor, cons


def test_consignment_estimated_payout_pinned_at_activation(api):
    """PRD §3.7: "A successful activation computes estimated_payout_cents from the current
    list_price_cents". PRD §3.7: "The first 5000 cents of the price are charged commission
    at 30 percent; the slice above 5000 and up to 20000 cents is charged at 20 percent".
    PRD §3.7: "estimated_payout_cents is not recomputed on a markdown — it stays pinned at
    the value computed at activation".

    Design: Difficulty/dual_variant_calc/consignment_estimated_vs_actual_payout
    """
    consignor, cons = _sold_marked_down_consignment(api)
    data = validate_success(api.get_consignment(cons["id"], MANAGER))
    # 10000: 5000*0.30=1500 + 5000*0.20=1000 = 2500 commission; payout 7500.
    assert data["estimated_payout_cents"] == 7500, f"got {data['estimated_payout_cents']}"


def test_consignment_actual_payout_from_marked_down_sale_price(api):
    """PRD §3.7: "The actual variant, computed at sale, uses sale_price_cents (the
    post-markdown price) and is what is credited to the consignor." PRD §3.7: "On that
    sale, sale_price_cents is set to the price on that order line (unit_price_cents),
    actual_payout_cents is computed from sale_price_cents, the consignor's store_credit_cents
    is credited by actual_payout_cents".

    Design: Difficulty/dual_variant_calc/consignment_estimated_vs_actual_payout
    """
    consignor, cons = _sold_marked_down_consignment(api)
    data = validate_success(api.get_consignment(cons["id"], MANAGER))
    # 8000: 5000*0.30=1500 + 3000*0.20=600 = 2100 commission; payout 5900.
    assert data["actual_payout_cents"] == 5900, f"got {data['actual_payout_cents']}"
    assert data["status"] == "SOLD", f"got {data['status']}"
    assert data["actual_payout_cents"] != data["estimated_payout_cents"]
    cust = validate_success(api.get_customer(consignor["id"], make_customer_headers(consignor["id"])))
    assert cust["store_credit_cents"] == 5900, f"consignor credited actual payout, got {cust['store_credit_cents']}"


# ---------------------------------------------------------------------------
# Queue A — display_slot_buffered_closed_interval_overlap (>=2 tests)
# ---------------------------------------------------------------------------
def _slot_with_active_booking_and_second_draft(api, second_start, second_end):
    consignor_a = register_customer(api, full_name="Consignor A")
    consignor_b = register_customer(api, full_name="Consignor B")
    product = create_product(api, artist="Slot Artist", title="Slot LP", format="VINYL",
                             base_price_cents=2000)
    slot = create_display_slot(api, slot_label="Front Window A")
    cons_a = create_consignment(
        api, consignor=consignor_a, product=product, list_price_cents=5000, condition_grade="VG",
        display_slot_id=slot["id"], display_start="2026-03-01T00:00:00Z",
        display_end="2026-03-10T00:00:00Z")
    validate_success(api.activate_consignment(cons_a["id"], MANAGER))
    cons_b = create_consignment(
        api, consignor=consignor_b, product=product, list_price_cents=5000, condition_grade="VG",
        display_slot_id=slot["id"], display_start=second_start, display_end=second_end)
    return cons_b


def test_display_slot_buffered_overlap_rejected(api):
    """PRD §3.7: "the requested closed-interval booking from display_start through
    display_end must not overlap another ACTIVE consignment on the same slot after each
    existing active booking has been expanded by a two-day buffer on both sides; an overlap
    under those buffered semantics is rejected with ERR_SLOT_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/display_slot_buffered_closed_interval_overlap
    """
    # Existing [Mar1,Mar10] expands to [Feb27,Mar12]; second [Mar11,Mar20] collides.
    cons_b = _slot_with_active_booking_and_second_draft(
        api, "2026-03-11T00:00:00Z", "2026-03-20T00:00:00Z")
    resp = api.activate_consignment(cons_b["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP.value)


def test_display_slot_overlap_leaves_second_in_draft(api):
    """PRD §3.7: "A Manager activates a consignment, moving it from DRAFT to ACTIVE."
    PRD §3.7: "an overlap under those buffered semantics is rejected with
    ERR_SLOT_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/display_slot_buffered_closed_interval_overlap
    """
    cons_b = _slot_with_active_booking_and_second_draft(
        api, "2026-03-11T00:00:00Z", "2026-03-20T00:00:00Z")
    validate_error(api.activate_consignment(cons_b["id"], MANAGER),
                   ApiErrorId.ERR_SLOT_OVERLAP.value)
    data = validate_success(api.get_consignment(cons_b["id"], MANAGER))
    assert data["status"] == "DRAFT", f"rejected activation must leave DRAFT, got {data['status']}"


# ---------------------------------------------------------------------------
# Queue B — slot_inactive_activation_rejected
# ---------------------------------------------------------------------------
def test_slot_inactive_activation_rejected(api):
    """PRD §3.7: "the targeted DisplaySlot must have is_active set to true; booking a
    retired slot is rejected with ERR_SLOT_INACTIVE (HTTP 409)."

    Design: Corner/validations/slot_inactive_activation_rejected
    """
    consignor = register_customer(api, full_name="Slot Inactive")
    product = create_product(api, artist="Sade", title="Diamond Life", format="VINYL",
                             base_price_cents=2000)
    slot = create_display_slot(api, slot_label="Retired B", is_active=False)
    cons = create_consignment(
        api, consignor=consignor, product=product, list_price_cents=5000, condition_grade="VG",
        display_slot_id=slot["id"], display_start="2026-03-01T00:00:00Z",
        display_end="2026-03-10T00:00:00Z")
    resp = api.activate_consignment(cons["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_SLOT_INACTIVE.value)
