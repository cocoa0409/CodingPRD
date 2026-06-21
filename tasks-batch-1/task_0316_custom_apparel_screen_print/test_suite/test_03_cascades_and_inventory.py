"""Cascade and inventory-conservation tests: the complete->fulfill->release->stock
depth-3 cascade, the cancel->release->restock depth-2 compensating cascade, the blank
and deposit conservation invariants, immediate consistency of reservation reads, and
BlankSku stock counters at create/restock.
"""
from test_helpers import (
    validate_success,
    setup_shop_catalog,
    setup_confirmed_order,
    setup_started_run,
    create_sku,
    create_style,
    create_shop,
    get_first_reservation,
    get_sku,
    get_order,
    get_customer,
    assert_blank_conservation_invariant,
    api_client,
    TEST_USERS,
)

SM = TEST_USERS["shop_manager_headers"]


# ═══════════════════════════════════════════════════════════════════════════
# transitive_cascade — complete -> fulfill -> consume -> stock (depth 3)
# ═══════════════════════════════════════════════════════════════════════════

def test_complete_cascades_fulfill_consume_and_returns_allowance(api):
    """PRD §3.8: "That advance settles every `ACTIVE` `BlankReservation` on the order
    to `CONSUMED`, because the order was actually produced. Each `CONSUMED` transition
    mutates the reservation's `BlankSku`: `on_hand_qty` rises by the run's
    `released_units` — the leftover allowance not used by the run, equal to
    `blanks_pulled` minus `good_units` minus `spoiled_units` — and the SKU's
    `reserved_qty` falls by the reservation's held `reserved_qty`, clearing the hold."

    Design: Difficulty/transitive_cascade/complete_fulfill_release_stock_depth3
    """
    cat = setup_shop_catalog(stock_qty=200)
    parts = setup_started_run(cat, size_run={"L": 50})  # ordered 50, allowance 3, reserved 53
    order_id = parts["order"]["id"]
    res_id = get_first_reservation(order_id)["id"]
    sku = cat["sku"]

    completed = validate_success(
        api.complete_run(order_id, parts["run"]["id"],
                         {"good_units": 50, "spoiled_units": 0}, SM), 200
    )
    assert completed["status"] == "COMPLETED"

    assert get_order(order_id)["fulfillment_status"] == "FULFILLED"

    reservation = validate_success(api.get_reservation(res_id, SM), 200)
    assert reservation["status"] == "CONSUMED"

    sku_after = get_sku(cat["style"]["id"], sku["id"])
    # released = 53 - 50 - 0 = 3; on_hand = 200 - 53 + 3 = 150; reserved -> 0
    assert sku_after["reserved_qty"] == 0
    assert sku_after["on_hand_qty"] == 150


def test_complete_run_records_released_units_and_marks_completed(api):
    """PRD §3.7: "the run moves from `RUNNING` to `COMPLETED` and cascades the order to
    `FULFILLED`".
    PRD §3.7: "sets `released_units` to `blanks_pulled` minus `consumed_units`, the
    unused allowance to be returned to stock."

    Design: Difficulty/transitive_cascade/complete_fulfill_release_stock_depth3
    """
    cat = setup_shop_catalog(stock_qty=200)
    parts = setup_started_run(cat, size_run={"L": 50})  # blanks_pulled 53
    completed = validate_success(
        api.complete_run(parts["order"]["id"], parts["run"]["id"],
                         {"good_units": 50, "spoiled_units": 0}, SM), 200
    )
    assert completed["status"] == "COMPLETED"
    assert completed["consumed_units"] == 50
    assert completed["released_units"] == 3  # 53 - 50


# ═══════════════════════════════════════════════════════════════════════════
# transitive_cascade — cancel -> release -> restock + proof void (depth 2)
# ═══════════════════════════════════════════════════════════════════════════

def test_cancel_releases_reservation_restores_stock_and_voids_proof(api):
    """PRD §3.8: "From `CONFIRMED` the cascade is fuller: every `ACTIVE`
    `BlankReservation` is moved to `RELEASED`, and each release mutates its `BlankSku`
    by lowering the SKU's `reserved_qty` by the reservation's `reserved_qty` and raising
    `on_hand_qty` by the same amount, returning the full hold to stock".

    Design: Difficulty/transitive_cascade/cancel_release_void_restock_depth2

    NOTE: The proof on a CONFIRMED order is APPROVED. Per PRD §3.8 only "every
    non-terminal `ArtProof` is voided to `VOID`" on cancel, and per PRD §3.3
    "`APPROVED` and `VOID` are the proof's terminal states". A terminal APPROVED
    proof is therefore NOT voided, so the proof-status assertion is omitted (it
    would contradict the PRD prose).
    """
    cat = setup_shop_catalog(stock_qty=200)
    parts = setup_confirmed_order(cat, size_run={"L": 50})  # reserved 53
    order_id = parts["order"]["id"]
    res_id = get_first_reservation(order_id)["id"]

    validate_success(api.cancel_order(order_id, SM), 200)

    reservation = validate_success(api.get_reservation(res_id, SM), 200)
    assert reservation["status"] == "RELEASED"

    sku_after = get_sku(cat["style"]["id"], cat["sku"]["id"])
    assert sku_after["on_hand_qty"] == 200
    assert sku_after["reserved_qty"] == 0


def test_cancel_drives_order_to_cancelled_terminal(api):
    """PRD §3.8: "Cancelling drives `fulfillment_status` to the terminal `CANCELLED`."
    PRD §3.8: "every `ACTIVE` `BlankReservation` is moved to `RELEASED`, and each
    release mutates its `BlankSku` by lowering the SKU's `reserved_qty` by the
    reservation's `reserved_qty` and raising `on_hand_qty` by the same amount, returning
    the full hold to stock".

    Design: Difficulty/transitive_cascade/cancel_release_void_restock_depth2
    """
    cat = setup_shop_catalog(stock_qty=200)
    parts = setup_confirmed_order(cat, size_run={"L": 50})  # reserved 53
    order_id = parts["order"]["id"]
    cancelled = validate_success(api.cancel_order(order_id, SM), 200)
    assert cancelled["fulfillment_status"] == "CANCELLED"
    sku_after = get_sku(cat["style"]["id"], cat["sku"]["id"])
    assert sku_after["reserved_qty"] == 0
    assert sku_after["on_hand_qty"] == 200


# ═══════════════════════════════════════════════════════════════════════════
# compensating_invariant — blank stock conserved across reserve/release pair
# ═══════════════════════════════════════════════════════════════════════════

def test_blank_stock_conserved_across_confirm_then_cancel(api):
    """PRD §2.8: "The governing invariant is that for every `BlankSku`, `on_hand_qty`
    plus the sum of `reserved_qty` over its `ACTIVE` reservations always equals
    `total_stock_qty`. This equality must hold before a confirm, after a confirm moves
    units from on-hand to reserved, and after a cancel moves them back — zero drift in
    blank units across the reserve-then-release compensating pair."

    Design: Difficulty/compensating_invariant/blank_stock_conserved_on_reserve_then_release
    """
    cat = setup_shop_catalog(stock_qty=200)
    parts = setup_confirmed_order(cat, size_run={"L": 50})
    order_id = parts["order"]["id"]

    sku_confirmed = get_sku(cat["style"]["id"], cat["sku"]["id"])
    assert_blank_conservation_invariant(sku_confirmed)  # 147 + 53 == 200

    validate_success(api.cancel_order(order_id, SM), 200)
    sku_after = get_sku(cat["style"]["id"], cat["sku"]["id"])
    assert sku_after["on_hand_qty"] == 200
    assert sku_after["reserved_qty"] == 0
    assert sku_after["on_hand_qty"] + sku_after["reserved_qty"] == sku_after["total_stock_qty"]
    assert sku_after["total_stock_qty"] == 200


def test_blank_invariant_holds_after_confirm_moves_units(api):
    """PRD §2.8: "This equality must hold before a confirm, after a confirm moves units
    from on-hand to reserved, and after a cancel moves them back".

    Design: Difficulty/compensating_invariant/blank_stock_conserved_on_reserve_then_release
    """
    cat = setup_shop_catalog(stock_qty=200)
    setup_confirmed_order(cat, size_run={"L": 50})  # reserves 53: on_hand 147, reserved 53
    sku = get_sku(cat["style"]["id"], cat["sku"]["id"])
    assert sku["on_hand_qty"] == 147
    assert sku["reserved_qty"] == 53
    assert_blank_conservation_invariant(sku)


# ═══════════════════════════════════════════════════════════════════════════
# compensating_invariant — customer deposit conserved across confirm/cancel
# ═══════════════════════════════════════════════════════════════════════════

def test_customer_deposit_charged_then_refunded(api):
    """PRD §3.4: "Confirmation sets the order's `deposit_paid_cents` to the ceiling of
    the quote's `grand_total_cents` times one half (0.5), adds that deposit to the owning
    customer's `outstanding_deposit_cents`".
    PRD §3.8: "the owning customer's `outstanding_deposit_cents` is decremented by the
    order's `deposit_paid_cents` as a compensating restoration of the conserved deposit
    total; and the order's `deposit_paid_cents` is reset to 0."

    Design: Difficulty/compensating_invariant/customer_deposit_conserved_on_confirm_then_cancel
    """
    cat = setup_shop_catalog(
        method_overrides={"extra_color_run_cents": 75, "screen_fee_cents": 2500},
        style_overrides={"blank_cost_cents": 350},
        stock_qty=200,
    )
    parts = setup_confirmed_order(
        cat, size_run={"L": 72}, line_overrides={"num_locations": 2, "num_colors": 3}
    )
    order_id = parts["order"]["id"]
    cust_id = cat["customer"]["id"]

    # grand_total 119400 -> deposit ceil(119400*0.5)=59700
    assert get_customer(cust_id)["outstanding_deposit_cents"] == 59700

    cancelled = validate_success(api.cancel_order(order_id, SM), 200)
    assert cancelled["deposit_paid_cents"] == 0
    assert get_customer(cust_id)["outstanding_deposit_cents"] == 0


def test_deposit_is_half_of_grand_total_at_confirm(api):
    """PRD §3.4: "Confirmation sets the order's `deposit_paid_cents` to the ceiling of
    the quote's `grand_total_cents` times one half (0.5), adds that deposit to the owning
    customer's `outstanding_deposit_cents`".

    Design: Difficulty/compensating_invariant/customer_deposit_conserved_on_confirm_then_cancel
    """
    cat = setup_shop_catalog(
        method_overrides={"extra_color_run_cents": 75, "screen_fee_cents": 2500},
        style_overrides={"blank_cost_cents": 350},
        stock_qty=200,
    )
    parts = setup_confirmed_order(
        cat, size_run={"L": 72}, line_overrides={"num_locations": 2, "num_colors": 3}
    )
    # grand_total 119400 -> deposit ceil(119400 * 0.5) = 59700
    assert parts["order"]["deposit_paid_cents"] == 59700


# ═══════════════════════════════════════════════════════════════════════════
# dual_variant_calc — reserved vs consumed on the BlankSku domain
# ═══════════════════════════════════════════════════════════════════════════

def test_reserved_vs_consumed_units_on_blanksku_domain(api):
    """PRD §3.7: "It then sets `consumed_units` to `good_units` plus `spoiled_units` —
    the blanks actually drawn from stock for keeps — and sets `released_units` to
    `blanks_pulled` minus `consumed_units`, the unused allowance to be returned to stock."

    Design: Difficulty/dual_variant_calc/blank_cost_reserved_vs_consumed_on_blanksku_domain
    """
    cat = setup_shop_catalog(style_overrides={"blank_cost_cents": 350}, stock_qty=200)
    parts = setup_started_run(cat, size_run={"L": 72})  # ordered 72, allowance 4, reserved 76
    order_id = parts["order"]["id"]
    res_id = get_first_reservation(order_id)["id"]

    completed = validate_success(
        api.complete_run(order_id, parts["run"]["id"],
                         {"good_units": 72, "spoiled_units": 2}, SM), 200
    )
    assert completed["blanks_pulled"] == 76
    assert completed["consumed_units"] == 74  # good 72 + spoiled 2
    assert completed["released_units"] == 2   # 76 - 74

    reservation = validate_success(api.get_reservation(res_id, SM), 200)
    assert reservation["status"] == "CONSUMED"


def test_consumed_blanks_leave_only_allowance_returns_to_stock(api):
    """PRD §3.8: "The blanks the run actually kept are gone from the shop; only the
    unused allowance returns to `on_hand_qty`."

    Design: Difficulty/dual_variant_calc/blank_cost_reserved_vs_consumed_on_blanksku_domain
    """
    cat = setup_shop_catalog(style_overrides={"blank_cost_cents": 350}, stock_qty=200)
    parts = setup_started_run(cat, size_run={"L": 72})  # reserved 76, on_hand 124
    order_id = parts["order"]["id"]
    validate_success(
        api.complete_run(order_id, parts["run"]["id"],
                         {"good_units": 72, "spoiled_units": 2}, SM), 200
    )
    sku_after = get_sku(cat["style"]["id"], cat["sku"]["id"])
    # on_hand = 200 - 76 pulled + 2 released = 126; reserved -> 0
    assert sku_after["on_hand_qty"] == 126
    assert sku_after["reserved_qty"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# consistency_model (corner) — reservation visible in same synchronous read
# ═══════════════════════════════════════════════════════════════════════════

def test_reservation_immediately_visible_after_confirm(api):
    """PRD §3.4: "Creating each reservation mutates its `BlankSku`: `reserved_qty` on the
    SKU rises by the reservation's `reserved_qty` and `on_hand_qty` falls by the same
    amount, preserving the conservation invariant of §2.8."

    Design: Corner/consistency_model/confirm_reservation_visible_same_response
    """
    cat = setup_shop_catalog(stock_qty=200)
    setup_confirmed_order(cat, size_run={"L": 50})  # reserved 53
    sku = get_sku(cat["style"]["id"], cat["sku"]["id"])
    assert sku["reserved_qty"] == 53
    assert sku["on_hand_qty"] == 147


# ═══════════════════════════════════════════════════════════════════════════
# entities (corner) — BlankSku stock at creation
# ═══════════════════════════════════════════════════════════════════════════

def test_blanksku_on_hand_equals_total_stock_at_creation(api):
    """PRD §2.8: "At creation `on_hand_qty` equals `total_stock_qty` and `reserved_qty`
    is 0."

    Design: Corner/entities/blanksku_on_hand_computed_on_create
    """
    shop = create_shop()
    style = create_style(shop["id"])
    sku = create_sku(style["id"], total_stock_qty=200)
    assert sku["on_hand_qty"] == 200
    assert sku["reserved_qty"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# endpoints (corner) — restock raises total and on_hand
# ═══════════════════════════════════════════════════════════════════════════

def test_restock_raises_total_and_on_hand(api):
    """PRD §3.1: "A restock supplies an `add_qty` that raises both `total_stock_qty` and
    `on_hand_qty` by that amount."

    Design: Corner/endpoints/restock_increases_stock_and_total
    """
    shop = create_shop()
    style = create_style(shop["id"])
    sku = create_sku(style["id"], total_stock_qty=200)
    restocked = validate_success(
        api.restock_blank_sku(style["id"], sku["id"], {"add_qty": 50}, SM), 200
    )
    assert restocked["total_stock_qty"] == 250
    assert restocked["on_hand_qty"] == 250
