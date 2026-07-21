"""Board builds and service tickets (the bench workshop surface).

Difficulty instances: board_build_provisional_vs_final_cost,
service_ticket_total_per_line_rounding_mode_b, build_reserve_stock_boundary_exact,
build_reserve_cancel_conserves_inventory_units, build_reserve_safety_beats_stock_fiscal.
Corner instance: board_build_complete_from_draft_returns_invalid_state.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
)
import test_helpers as th

SM = TEST_USERS["shop_manager_headers"]
BT = TEST_USERS["bench_tech_headers"]
SA = TEST_USERS["sales_associate_headers"]


# --------------------------------------------------------------------------- #
# Difficulty: board build provisional vs final cost (dual variant)
# --------------------------------------------------------------------------- #
def _deck_and_wheels_build(api):
    """Deck @7999 (on_hand 10) + Wheels @2995 (on_hand 10); DRAFT build with one of each."""
    customer = th.create_customer(api, email="bb1@x.com", full_name="Build One")
    deck = th.create_product_with_stock(api, 10, sku="DECK-1", name="Deck", category="DECK", unit_price_cents=7999)
    whl = th.create_product_with_stock(api, 10, sku="WHL-1", name="Wheels", category="WHEELS", unit_price_cents=2995)
    build = th.create_draft_board_build(
        api, customer["id"],
        [{"product_id": deck["id"], "qty": 1}, {"product_id": whl["id"], "qty": 1}],
    )
    return build


def test_board_build_provisional_cost_at_reserve(api):
    """PRD §3.5: "The provisional cost, set at reservation, is the plain list-price sum with no bundle discount: for each component the product's `unit_price_cents` is multiplied by its `qty`, those line amounts are summed, and a fixed build labor charge of 2500 cents is added."

    Design: Difficulty/dual_variant_calc/board_build_provisional_vs_final_cost
    """
    build = _deck_and_wheels_build(api)
    resp = api.reserve_board_build(build["id"], BT)
    data = validate_success(resp, expected_status=200)
    # (7999 + 2995) + 2500 = 13494
    assert data["provisional_cost_cents"] == 13494
    assert data["status"] == "RESERVED"


def test_board_build_final_cost_differs_from_provisional(api):
    """PRD §3.5: "The final cost applies a 10% per-line bundle discount in a pinned order: for each component, multiply the product's `unit_price_cents` by the line `qty` and by nine-tenths (one minus the 10% bundle discount), round that line half up to whole cents, then sum the rounded lines, and finally add the same 2500-cent labor charge (labor is neither discounted nor taxed)."
    PRD §3.5: "The per-line rounding before summing is authoritative, so the final cost may differ from the provisional cost for the identical set of components."

    Design: Difficulty/dual_variant_calc/board_build_provisional_vs_final_cost
    """
    build = _deck_and_wheels_build(api)
    validate_success(api.reserve_board_build(build["id"], BT))
    resp = api.complete_board_build(build["id"], BT)
    data = validate_success(resp, expected_status=200)
    # round(7199.1)=7199 + round(2695.5)=2696 + 2500 = 12395
    assert data["final_cost_cents"] == 12395
    assert data["provisional_cost_cents"] == 13494
    assert data["final_cost_cents"] != data["provisional_cost_cents"]


# --------------------------------------------------------------------------- #
# Difficulty: service ticket total per-line rounding (nested rounding)
# --------------------------------------------------------------------------- #
def test_service_ticket_total_per_line_taxed_rounding(api):
    """PRD §3.6: "Each part line's `unit_price_cents` is multiplied by its `qty` and by one plus the tax rate of 0.0725, and that line is rounded half up to whole cents; the taxed part lines are then summed. Separately, the `labor_cents` is multiplied by one plus the same tax rate and rounded half up to whole cents to form the labor line. The `total_cents` is the sum of the taxed part-line total and the taxed labor line."

    Design: Difficulty/combinatorial_formula/service_ticket_total_per_line_rounding_mode_b
    """
    customer = th.create_customer(api, email="svc@x.com", full_name="Svc Sue")
    p1 = th.create_product(api, sku="GRIP-1", name="Grip Tape", category="GRIP", unit_price_cents=1299)
    p2 = th.create_product(api, sku="WAX-1", name="Surf Wax", category="WAX", unit_price_cents=899)
    ticket = th.create_service_ticket(
        api, customer["id"],
        [{"product_id": p1["id"], "qty": 2, "unit_price_cents": 1299},
         {"product_id": p2["id"], "qty": 1, "unit_price_cents": 899}],
        4000,
    )
    resp = api.ready_service_ticket(ticket["id"], BT)
    data = validate_success(resp, expected_status=200)
    # line1=round(2786.355)=2786 ; line2=round(964.1775)=964 ; labor=round(4290.0)=4290 -> 8040
    assert data["total_cents"] == 8040
    assert data["status"] == "READY"


def test_service_ticket_per_line_order_beats_sum_then_tax(api):
    """PRD §3.6: "The per-line taxing-and-rounding order is authoritative — the total is not computed by summing raw subtotals and taxing once at the end."

    Design: Difficulty/combinatorial_formula/service_ticket_total_per_line_rounding_mode_b
    """
    customer = th.create_customer(api, email="svc2@x.com", full_name="Svc Sam")
    p1 = th.create_product(api, sku="GRIP-2", name="Grip Tape 2", category="GRIP", unit_price_cents=1299)
    p2 = th.create_product(api, sku="WAX-2", name="Surf Wax 2", category="WAX", unit_price_cents=899)
    ticket = th.create_service_ticket(
        api, customer["id"],
        [{"product_id": p1["id"], "qty": 2, "unit_price_cents": 1299},
         {"product_id": p2["id"], "qty": 1, "unit_price_cents": 899}],
        4000,
    )
    data = validate_success(api.ready_service_ticket(ticket["id"], BT))
    # Per-line total is 8040; the (rejected) sum-then-tax variant would give 8041.
    assert data["total_cents"] == 8040
    assert data["total_cents"] != 8041


# --------------------------------------------------------------------------- #
# Difficulty: build reserve stock boundary (inclusive >=)
# --------------------------------------------------------------------------- #
def test_build_reserve_qty_equal_to_available_succeeds(api):
    """PRD §3.5: "Second, every component must have sufficient stock — each component's product `available_qty` must be greater than or equal to that component's line `qty`; if any falls short, the reservation is refused with `ERR_INSUFFICIENT_STOCK`."
    PRD §3.5: "When both hold, the build moves from `DRAFT` to `RESERVED`, its provisional cost is computed, and for each component the product's `reserved_qty` is increased by the line `qty` and its `available_qty` is reconciled."

    Design: Difficulty/boundary_precision_check/build_reserve_stock_boundary_exact
    """
    customer = th.create_customer(api, email="bnd@x.com", full_name="Boundary Bo")
    prod = th.create_product_with_stock(api, 5, sku="WHL-B", name="Wheels B", category="WHEELS", unit_price_cents=3000)
    build = th.create_draft_board_build(api, customer["id"], [{"product_id": prod["id"], "qty": 5}])
    data = validate_success(api.reserve_board_build(build["id"], BT))
    assert data["status"] == "RESERVED"
    prod_read = validate_success(api.get_product(prod["id"], BT))
    assert prod_read["available_qty"] == 0
    assert prod_read["reserved_qty"] == 5


def test_build_reserve_qty_over_available_rejected(api):
    """PRD §3.5: "Second, every component must have sufficient stock — each component's product `available_qty` must be greater than or equal to that component's line `qty`; if any falls short, the reservation is refused with `ERR_INSUFFICIENT_STOCK`."

    Design: Difficulty/boundary_precision_check/build_reserve_stock_boundary_exact
    """
    customer = th.create_customer(api, email="bnd2@x.com", full_name="Boundary Bea")
    prod = th.create_product_with_stock(api, 5, sku="WHL-B2", name="Wheels B2", category="WHEELS", unit_price_cents=3000)
    build_a = th.create_draft_board_build(api, customer["id"], [{"product_id": prod["id"], "qty": 5}])
    validate_success(api.reserve_board_build(build_a["id"], BT))  # drives available to 0
    build_b = th.create_draft_board_build(api, customer["id"], [{"product_id": prod["id"], "qty": 1}])
    resp = api.reserve_board_build(build_b["id"], BT)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)
    reread = validate_success(api.get_board_build(build_b["id"], BT))
    assert reread["status"] == "DRAFT"


# --------------------------------------------------------------------------- #
# Difficulty: compensating invariant (reserve+cancel conserves inventory)
# --------------------------------------------------------------------------- #
def test_reserved_build_cancel_restores_inventory(api):
    """PRD §3.5: "If the build was `RESERVED` at the time of cancellation, the reservation is compensatingly released: for each component the product's `reserved_qty` is decreased by the line `qty` and `available_qty` is reconciled, while `on_hand_qty` is left unchanged."

    Design: Difficulty/compensating_invariant/build_reserve_cancel_conserves_inventory_units
    """
    customer, prod, build = th.setup_reserved_board_build(api, on_hand=8, qty=3, unit_price_cents=5000)
    resp = api.cancel_board_build(build["id"], BT)
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "CANCELLED"
    prod_read = validate_success(api.get_product(prod["id"], BT))
    assert prod_read["on_hand_qty"] == 8
    assert prod_read["reserved_qty"] == 0
    assert prod_read["available_qty"] == 8


def test_draft_build_cancel_releases_nothing(api):
    """PRD §3.5: "Cancelling a build that was still `DRAFT` releases nothing, since no stock was ever reserved."

    Design: Difficulty/compensating_invariant/build_reserve_cancel_conserves_inventory_units
    """
    customer = th.create_customer(api, email="drc@x.com", full_name="Draft Cancel")
    prod = th.create_product_with_stock(api, 8, sku="TRK-D", name="Trucks D", category="TRUCKS", unit_price_cents=5000)
    build = th.create_draft_board_build(api, customer["id"], [{"product_id": prod["id"], "qty": 3}])
    data = validate_success(api.cancel_board_build(build["id"], BT))
    assert data["status"] == "CANCELLED"
    prod_read = validate_success(api.get_product(prod["id"], BT))
    assert prod_read["on_hand_qty"] == 8
    assert prod_read["reserved_qty"] == 0
    assert prod_read["available_qty"] == 8


# --------------------------------------------------------------------------- #
# Difficulty: priority conflict — safety (discontinued) beats fiscal (stock)
# --------------------------------------------------------------------------- #
def test_reserve_discontinued_and_out_of_stock_returns_component_incompatible(api):
    """PRD §3.5: "First, no component product may be `DISCONTINUED`; if any is, the reservation is refused with `ERR_COMPONENT_INCOMPATIBLE`. Second, every component must have sufficient stock — each component's product `available_qty` must be greater than or equal to that component's line `qty`; if any falls short, the reservation is refused with `ERR_INSUFFICIENT_STOCK`."

    Design: Difficulty/priority_pair_validation_conflict/build_reserve_safety_beats_stock_fiscal
    """
    customer = th.create_customer(api, email="pv2@x.com", full_name="Prio Two")
    prod = th.create_product(api, sku="DECK-D", name="Deck D", category="DECK", unit_price_cents=8000)
    validate_success(api.discontinue_product(prod["id"], SM))  # on_hand stays 0 (out of stock too)
    build = th.create_draft_board_build(api, customer["id"], [{"product_id": prod["id"], "qty": 1}])
    resp = api.reserve_board_build(build["id"], BT)
    validate_error(resp, ApiErrorId.ERR_COMPONENT_INCOMPATIBLE.value)
    reread = validate_success(api.get_board_build(build["id"], BT))
    assert reread["status"] == "DRAFT"


def test_reserve_active_but_insufficient_stock_returns_insufficient_stock(api):
    """PRD §3.5: "Second, every component must have sufficient stock — each component's product `available_qty` must be greater than or equal to that component's line `qty`; if any falls short, the reservation is refused with `ERR_INSUFFICIENT_STOCK`."

    Design: Difficulty/priority_pair_validation_conflict/build_reserve_safety_beats_stock_fiscal
    """
    customer = th.create_customer(api, email="pv3@x.com", full_name="Prio Three")
    prod = th.create_product(api, sku="DECK-E", name="Deck E", category="DECK", unit_price_cents=8000)  # on_hand 0, ACTIVE
    build = th.create_draft_board_build(api, customer["id"], [{"product_id": prod["id"], "qty": 1}])
    resp = api.reserve_board_build(build["id"], BT)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)
    reread = validate_success(api.get_board_build(build["id"], BT))
    assert reread["status"] == "DRAFT"


# --------------------------------------------------------------------------- #
# Corner: complete-from-draft invalid state
# --------------------------------------------------------------------------- #
def test_complete_build_still_in_draft_returns_invalid_state(api):
    """PRD §3.5: "Completing a reserved build (a `BenchTech` or `ShopManager` action) requires the build to be `RESERVED`, else `ERR_BUILD_INVALID_STATE`."

    Design: Corner/state_machines/board_build_complete_from_draft_returns_invalid_state
    """
    customer = th.create_customer(api, email="sm1@x.com", full_name="SM One")
    prod = th.create_product_with_stock(api, 5, sku="DECK-SM", name="Deck SM", category="DECK", unit_price_cents=8000)
    build = th.create_draft_board_build(api, customer["id"], [{"product_id": prod["id"], "qty": 1}])
    resp = api.complete_board_build(build["id"], BT)
    validate_error(resp, ApiErrorId.ERR_BUILD_INVALID_STATE.value)
    reread = validate_success(api.get_board_build(build["id"], BT))
    assert reread["status"] == "DRAFT"
