"""Cross-entity state dependencies, resource temporal/capacity overlap, and
compensating-release invariants.

Difficulty queue: cross_entity_state_dependency, resource_temporal_overlap,
compensating_invariant.
"""
import pytest
from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    create_store,
    create_sku,
    create_customer,
    stock_sku,
    create_inventory_row,
    create_markdown,
    create_markdown_payload,
    issue_fishing_license,
    setup_placed_order,
    setup_ready_order,
    setup_fulfilled_order,
    create_draft_order,
    add_order_line,
    place_order,
    ready_order,
    fulfill_order,
    submit_price_match_claim,
    make_customer_headers,
    setup_started_service_ticket,
    get_inventory,
    get_order,
    get_service_ticket,
    TEST_USERS,
)

PRICE_ADMIN = TEST_USERS["price_admin_headers"]
TECH = TEST_USERS["service_tech_headers"]


# ===========================================================================
# cross_entity_state_dependency / order_place_requires_active_license_order_to_license
# ===========================================================================
def test_place_license_gated_line_succeeds_with_active_license(api):
    """PRD §3.4: "A line whose SKU has `requires_license_permit` true may only be
    placed if the placing customer holds a fishing license that is `ACTIVE` and was
    issued at the order's `store_id`."

    With an ACTIVE license issued at the order's store, placing the license-gated
    line succeeds (DRAFT -> RESERVED).

    Design: Difficulty/cross_entity_state_dependency/order_place_requires_active_license_order_to_license
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="FISHING", name="Permit Tackle", base_price_cents=3000,
                     size_label="NA", requires_license_permit=True)
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 5)
    issue_fishing_license(customer["id"], store["id"])

    placed, _ = setup_placed_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}]
    )
    assert placed["fulfillment_status"] == "RESERVED"


def test_place_license_gated_line_blocked_without_license(api):
    """PRD §3.4: "If such a line is present at placement and no qualifying active
    license exists for that store, the placement is rejected with
    `ERR_LICENSE_REQUIRED`."

    The same license-gated line, stocked but with no license held, is rejected —
    the order's transition depends on FishingLicense state.

    Design: Difficulty/cross_entity_state_dependency/order_place_requires_active_license_order_to_license
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="FISHING", name="Permit Tackle", base_price_cents=3000,
                     size_label="NA", requires_license_permit=True)
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 5)

    order = create_draft_order(customer["id"], store["id"])
    add_order_line(order["id"], customer["id"], sku["id"], 1)
    res = api.place_order(order["id"], make_customer_headers(customer["id"]))
    validate_error(res, "ERR_LICENSE_REQUIRED", expected_status=422)


# ===========================================================================
# cross_entity_state_dependency / pricematch_approve_requires_order_prefulfillment_claim_to_order
# ===========================================================================
def test_price_match_approve_blocked_on_fulfilled_order(api):
    """PRD §3.7: "A claim against an order that is `FULFILLED` or `CANCELLED` is
    rejected with `ERR_ORDER_NOT_MATCHABLE`".

    A claim is submitted while the order is pre-fulfillment, the order is then
    fulfilled, and approval fails with ERR_ORDER_NOT_MATCHABLE — the claim's
    transition depends on the referenced Order's fulfillment_status.

    Design: Difficulty/cross_entity_state_dependency/pricematch_approve_requires_order_prefulfillment_claim_to_order
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="BASEBALL", name="Bat", base_price_cents=7000, size_label="33in")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 5)

    # Build order, add line, submit a claim BEFORE placement, then fulfill the order.
    order = create_draft_order(customer["id"], store["id"])
    line = add_order_line(order["id"], customer["id"], sku["id"], 1)
    claim = submit_price_match_claim(order["id"], line["id"], customer["id"], 5000)

    place_order(order["id"], customer["id"])
    ready_order(order["id"])
    fulfill_order(order["id"])

    res = api.approve_price_match_claim(claim["id"], PRICE_ADMIN)
    validate_error(res, "ERR_ORDER_NOT_MATCHABLE", expected_status=409)


def test_price_match_approve_allowed_on_reserved_order(api):
    """PRD §3.7: "Approval is permitted only when the claim is `SUBMITTED`, when the
    referenced order is still pre-fulfillment with `fulfillment_status` in `DRAFT`,
    `RESERVED`, or `READY`".

    A claim against a RESERVED (pre-fulfillment) order approves successfully,
    confirming the cross-entity precondition is satisfied for the pre-fulfillment
    states.

    Design: Difficulty/cross_entity_state_dependency/pricematch_approve_requires_order_prefulfillment_claim_to_order
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="BASEBALL", name="Bat", base_price_cents=7000, size_label="33in")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 5)

    placed, lines = setup_placed_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}]
    )
    assert placed["fulfillment_status"] == "RESERVED"
    claim = submit_price_match_claim(placed["id"], lines[0]["id"], customer["id"], 5000)

    res = api.approve_price_match_claim(claim["id"], PRICE_ADMIN)
    approved = get_success_data(res)
    assert approved["status"] == "APPROVED"


# ===========================================================================
# resource_temporal_overlap / markdown_window_overlap_rejected_half_open
# ===========================================================================
def test_markdown_overlapping_window_rejected(api):
    """PRD §3.2: "Two markdowns on the same SKU may not have overlapping
    `[effective_from, effective_until)` windows; because the windows are half-open,
    two windows that merely touch at a single shared instant do not overlap and are
    allowed, but any genuine overlap is rejected with `ERR_MARKDOWN_OVERLAP`."

    A second markdown whose window [2026-03-15, 2026-05-01) overlaps an existing
    [2026-03-01, 2026-04-01) by a positive measure is rejected.

    Design: Difficulty/resource_temporal_overlap/markdown_window_overlap_rejected_half_open
    """
    sku = create_sku(sport="APPAREL", name="Hoodie", base_price_cents=6000, size_label="L")
    create_markdown(sku["id"], "SEASONAL", 20, "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z")

    res = api.create_markdown(
        create_markdown_payload(sku["id"], "CLEARANCE", 40,
                                "2026-03-15T00:00:00Z", "2026-05-01T00:00:00Z"),
        PRICE_ADMIN,
    )
    validate_error(res, "ERR_MARKDOWN_OVERLAP", expected_status=409)


def test_markdown_touching_window_allowed_half_open(api):
    """PRD §3.2: "because the windows are half-open, two windows that merely touch
    at a single shared instant do not overlap and are allowed".

    A second markdown starting exactly at the first's effective_until
    (2026-04-01) is adjacent-touching, not overlapping, and is accepted.

    Design: Difficulty/resource_temporal_overlap/markdown_window_overlap_rejected_half_open
    """
    sku = create_sku(sport="APPAREL", name="Hoodie", base_price_cents=6000, size_label="L")
    create_markdown(sku["id"], "SEASONAL", 20, "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z")

    res = api.create_markdown(
        create_markdown_payload(sku["id"], "CLEARANCE", 40,
                                "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z"),
        PRICE_ADMIN,
    )
    second = get_success_data(res)
    assert second["markdown_kind"] == "CLEARANCE"


# ===========================================================================
# resource_temporal_overlap / inventory_aggregate_capacity_overlap_two_reservations
# (also owns corner stub: insufficient_inventory_violation_on_place)
# ===========================================================================
def test_second_reservation_exceeding_capacity_rejected(api):
    """PRD §2.5: "A reservation may only proceed when the affected row's
    `available_qty` is at least the number of units requested; a request that would
    reserve more than is available is rejected with `ERR_INSUFFICIENT_INVENTORY`."
    PRD §3.3: "If any line cannot be covered by available stock, the placement is
    rejected with `ERR_INSUFFICIENT_INVENTORY`."

    Stocked with 3 units; first order line qty 2 placed (reserved 2, available 1).
    A second order line qty 2 cannot be placed (available 1 < 2) and is rejected;
    the row's reserved_qty stays at 2 (second reservation not applied).

    Design: Difficulty/resource_temporal_overlap/inventory_aggregate_capacity_overlap_two_reservations
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="FOOTWEAR", name="Runners", base_price_cents=8000, size_label="9D")
    customer = create_customer(home_state_code="CA")
    inv = stock_sku(store["id"], sku["id"], 3)

    setup_placed_order(customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 2}])

    order2 = create_draft_order(customer["id"], store["id"])
    add_order_line(order2["id"], customer["id"], sku["id"], 2)
    res = api.place_order(order2["id"], make_customer_headers(customer["id"]))
    validate_error(res, "ERR_INSUFFICIENT_INVENTORY", expected_status=409)

    inv_after = get_inventory(inv["id"])
    assert inv_after["reserved_qty"] == 2


def test_two_reservations_coexist_within_capacity(api):
    """PRD §2.5: "The `reserved_qty` is the count of units soft-held by non-terminal
    order lines and active service-ticket part holds; it is increased when units are
    reserved and decreased when they are committed or released."

    Two reservations may coexist while their summed quantities fit available_qty:
    with 3 units stocked, a qty-2 and then a qty-1 reservation both succeed,
    driving reserved_qty to 3 and available_qty to 0.

    Design: Difficulty/resource_temporal_overlap/inventory_aggregate_capacity_overlap_two_reservations
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="FOOTWEAR", name="Runners", base_price_cents=8000, size_label="9D")
    customer = create_customer(home_state_code="CA")
    inv = stock_sku(store["id"], sku["id"], 3)

    setup_placed_order(customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 2}])
    setup_placed_order(customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}])

    inv_after = get_inventory(inv["id"])
    assert inv_after["reserved_qty"] == 3
    assert inv_after["available_qty"] == 0


# ===========================================================================
# compensating_invariant / order_cancel_releases_reservation_onhand_conserved
# ===========================================================================
def test_order_cancel_releases_reservation_conserves_on_hand(api):
    """PRD §3.3: "Cancelling a `RESERVED` or a `READY` order runs the release
    compensation: for each line, the stock row's `reserved_qty` is lowered by the
    line's `quantity`, `available_qty` is recomputed, and the line's `line_status`
    moves `RESERVED → RELEASED`; `on_hand_qty` is left unchanged so `reserved_qty`
    returns to its pre-placement value."

    Stocked 5 units; line qty 3 placed (reserved 3); cancel returns reserved_qty to
    0 with on_hand_qty conserved at 5 and available_qty back to 5.

    Design: Difficulty/compensating_invariant/order_cancel_releases_reservation_onhand_conserved
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="BASEBALL", name="Helmet", base_price_cents=4000, size_label="M")
    customer = create_customer(home_state_code="CA")
    inv = stock_sku(store["id"], sku["id"], 5)

    placed, _ = setup_placed_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 3}]
    )
    get_success_data(api.cancel_order(placed["id"], make_customer_headers(customer["id"])))

    inv_after = get_inventory(inv["id"])
    assert inv_after["on_hand_qty"] == 5
    assert inv_after["reserved_qty"] == 0
    assert inv_after["available_qty"] == 5


def test_order_cancel_refunds_authorization(api):
    """PRD §3.3: "The payment axis moves `AUTHORIZED → REFUNDED`, voiding the
    authorization hold so that the net captured amount is zero, and the order's
    `version` increments by one."

    Cancelling a RESERVED order moves the payment axis to REFUNDED — the payment
    arm of the release compensation.

    Design: Difficulty/compensating_invariant/order_cancel_releases_reservation_onhand_conserved
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="BASEBALL", name="Helmet", base_price_cents=4000, size_label="M")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 5)

    placed, _ = setup_placed_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 3}]
    )
    cancelled = get_success_data(
        api.cancel_order(placed["id"], make_customer_headers(customer["id"]))
    )
    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "REFUNDED"


# ===========================================================================
# compensating_invariant / service_cancel_releases_part_payment_quantity_conserved
# ===========================================================================
def test_service_cancel_releases_part_conserves_on_hand(api):
    """PRD §3.8: "Cancelling from `IN_PROGRESS` or from `NEEDS_PARTS` releases any
    reserved part by lowering the part's stock row `reserved_qty` by 1 and
    recomputing `available_qty`, leaving `on_hand_qty` unchanged."

    A RACKET_STRING ticket with a part stocked at 4 units is started (reserved 1,
    available 3); cancelling from IN_PROGRESS returns reserved_qty to 0 with
    on_hand_qty conserved at 4 and available_qty back to 4.

    Design: Difficulty/compensating_invariant/service_cancel_releases_part_payment_quantity_conserved
    """
    store = create_store(state_code="CA")
    part_sku = create_sku(sport="APPAREL", name="Gut String", base_price_cents=1800, size_label="NA")
    customer = create_customer(home_state_code="CA")
    inv = stock_sku(store["id"], part_sku["id"], 4)

    ticket = setup_started_service_ticket(
        customer["id"], store["id"], "RACKET_STRING", part_sku_id=part_sku["id"]
    )
    assert ticket["status"] == "IN_PROGRESS"

    cancelled = get_success_data(api.cancel_service_ticket(ticket["id"], TECH))
    assert cancelled["status"] == "CANCELLED"

    inv_after = get_inventory(inv["id"])
    assert inv_after["on_hand_qty"] == 4
    assert inv_after["reserved_qty"] == 0
    assert inv_after["available_qty"] == 4


def test_service_start_reserves_one_part_unit(api):
    """PRD §3.8: "if a part is named, the start requires the part's stock row to
    have `available_qty` of at least 1, and on success reserves one unit by raising
    that row's `reserved_qty` by 1 and recomputing `available_qty`."

    Starting the RACKET_STRING ticket reserves exactly one part unit (reserved 1,
    available 3 from 4 on_hand) — the precondition the cancel-release invariant
    later compensates.

    Design: Difficulty/compensating_invariant/service_cancel_releases_part_payment_quantity_conserved
    """
    store = create_store(state_code="CA")
    part_sku = create_sku(sport="APPAREL", name="Gut String", base_price_cents=1800, size_label="NA")
    customer = create_customer(home_state_code="CA")
    inv = stock_sku(store["id"], part_sku["id"], 4)

    setup_started_service_ticket(
        customer["id"], store["id"], "RACKET_STRING", part_sku_id=part_sku["id"]
    )
    inv_after = get_inventory(inv["id"])
    assert inv_after["reserved_qty"] == 1
    assert inv_after["available_qty"] == 3
    assert inv_after["on_hand_qty"] == 4
