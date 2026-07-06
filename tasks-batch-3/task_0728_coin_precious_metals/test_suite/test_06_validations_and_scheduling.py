"""Business-rule validations (bullion premium, overpayment, insufficient
inventory, reserve, IRA precondition) and the two temporal-overlap regimes
(half-open auction rooms vs closed appraiser intervals).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    set_spot_rate,
    create_product,
    create_inventory_lot,
    create_customer,
    create_placed_sell_order,
    create_intake_consignment,
    setup_layaway,
    setup_listed_consignment,
    create_auction_session,
    deposit_on_layaway,
    make_customer_headers,
    TEST_USERS,
)

TRADER = TEST_USERS["trader_headers"]
SALES = TEST_USERS["sales_agent_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── Corner: bullion product with premium forbidden ───────────────────────

def test_bullion_product_with_premium_forbidden(api):
    """PRD §3.1: "a BULLION product must be created with numismatic_premium_cents
    equal to 0; an attempt to create a BULLION product with a premium above 0 is
    rejected with ERR_BULLION_PREMIUM_FORBIDDEN (HTTP 422)."

    Design: Corner/validations/bullion_product_with_premium_returns_forbidden
    """
    res = api.create_product(
        {"sku": "AU-BADPREM", "product_type": "BULLION", "metal": "GOLD",
         "weight_troy_oz": 1.0, "purity": 1.0, "min_sell_spread_pct": 0.05,
         "buy_spread_pct": 0.04, "numismatic_premium_cents": 5000}, TRADER)
    validate_error(res, "ERR_BULLION_PREMIUM_FORBIDDEN")


# ─── Corner: overpayment deposit rejected (upper boundary) ────────────────

def test_overpayment_deposit_rejected(api):
    """PRD §3.5: "A deposit that would push amount_paid_cents above total_price_cents
    is rejected as an overpayment with ERR_OVERPAYMENT (HTTP 422), though paying
    exactly the remaining balance is allowed."

    Design: Corner/validations/overpayment_deposit_returns_overpayment_error
    """
    ctx = setup_layaway(quantity=2, customer_name="Overpayer")
    lay = ctx["layaway"]  # total_price 420000
    res = api.deposit_layaway(
        lay["id"], {"amount_cents": 500_000, "expected_layaway_version": lay["version"]},
        make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_OVERPAYMENT")
    unchanged = validate_success(api.get_layaway(lay["id"], SALES), 200)
    assert unchanged["amount_paid_cents"] == 0


# ─── Corner: exact-remaining deposit succeeds (equal boundary) ────────────

def test_exact_full_deposit_allowed(api):
    """PRD §3.5: "the new cumulative total would not exceed the price: that is,
    amount_paid_cents plus amount_cents must be at most total_price_cents." PRD §3.5:
    "paying exactly the remaining balance is allowed."

    Design: Corner/validations/exact_remaining_deposit_succeeds_boundary
    """
    ctx = setup_layaway(quantity=2, customer_name="Exact Payer")
    lay = ctx["layaway"]  # total_price 420000
    after = deposit_on_layaway(lay["id"], 420_000, lay["version"], ctx["customer"]["id"])
    assert after["amount_paid_cents"] == 420_000
    assert after["status"] == "ACTIVE"


# ─── Corner + Rule 6b: insufficient inventory at settle ───────────────────

def test_sell_settle_insufficient_inventory_boundary(api):
    """PRD §3.3: "The aggregate available_qty across the product's AVAILABLE lots
    must be at least the order quantity — if the product has no available inventory
    or too little, settlement fails with ERR_INSUFFICIENT_INVENTORY (HTTP 422)."

    Design: Difficulty/boundary_precision_check/insufficient_inventory_empty_and_zero_boundary
    """
    set_spot_rate("GOLD", 200_000)
    product = create_product(sku="AU-1OZ-B5", product_type="BULLION", metal="GOLD",
                             weight_troy_oz=1.0, purity=1.0, min_sell_spread_pct=0.05,
                             buy_spread_pct=0.04)
    create_inventory_lot(product["id"], total_qty=1, acquisition_unit_cost_cents=100_000)
    customer = create_customer("Overreach Buyer")
    order = create_placed_sell_order(product["id"], customer["id"], quantity=2)

    res = api.settle_sell_order(order["id"], SALES)
    validate_error(res, "ERR_INSUFFICIENT_INVENTORY")
    stayed = validate_success(api.get_sell_order(order["id"], SALES), 200)
    assert stayed["status"] == "PLACED"


def test_sell_settle_succeeds_at_exact_available(api):
    """PRD §3.3: "The aggregate available_qty across the product's AVAILABLE lots
    must be at least the order quantity". PRD §3.3: "Once these checks pass, the
    system computes final_cogs_cents by the FIFO consumption ... Finally the order
    status becomes SETTLED."

    Design: Difficulty/boundary_precision_check/insufficient_inventory_empty_and_zero_boundary
    """
    set_spot_rate("GOLD", 200_000)
    product = create_product(sku="AU-1OZ-B5B", product_type="BULLION", metal="GOLD",
                             weight_troy_oz=1.0, purity=1.0, min_sell_spread_pct=0.05,
                             buy_spread_pct=0.04)
    create_inventory_lot(product["id"], total_qty=2, acquisition_unit_cost_cents=100_000)
    customer = create_customer("Exact Buyer")
    order = create_placed_sell_order(product["id"], customer["id"], quantity=2)

    settled = validate_success(api.settle_sell_order(order["id"], SALES), 200)
    assert settled["status"] == "SETTLED"


# ─── Corner: record-sale below reserve ────────────────────────────────────

def test_record_sale_below_reserve_rejected(api):
    """PRD §3.6: "a hammer price below reserve is rejected with ERR_RESERVE_NOT_MET
    (HTTP 422), and meeting the reserve exactly is allowed."

    Design: Corner/errors/reserve_not_met_below_reserve_returns_error
    """
    ctx = setup_listed_consignment(room="ROOM-RES", reserve_price_cents=50_000,
                                   customer_name="Reserve Consignor",
                                   description="Below reserve item")
    cons_id = ctx["consignment"]["id"]
    res = api.record_sale_consignment(
        cons_id, {"hammer_price_cents": 49_999,
                  "expected_consignment_version": ctx["listed_version"]}, SALES)
    validate_error(res, "ERR_RESERVE_NOT_MET")
    stayed = validate_success(api.get_consignment(cons_id, SALES), 200)
    assert stayed["status"] == "LISTED"


# ─── Rule 8a: auction room half-open overlap ──────────────────────────────

def test_auction_room_overlap_rejected(api):
    """PRD §3.8: "Two sessions in the same room may not overlap in time, but unlike
    appraisal appointments these intervals are half-open, spanning from the start up
    to but not including the end ... whereas any genuine overlap is rejected with
    ERR_ROOM_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/auction_room_half_open_overlap
    """
    create_auction_session(room="ROOM-X", scheduled_start="2026-04-05T10:00:00Z",
                           scheduled_end="2026-04-05T12:00:00Z")
    res = api.create_auction_session(
        {"room": "ROOM-X", "scheduled_start": "2026-04-05T11:00:00Z",
         "scheduled_end": "2026-04-05T13:00:00Z"}, SALES)
    validate_error(res, "ERR_ROOM_DOUBLE_BOOKED")


def test_auction_room_touching_boundary_allowed(api):
    """PRD §3.8: "these intervals are half-open, spanning from the start up to but
    not including the end; a session that begins exactly when another ends therefore
    does not collide".

    Design: Difficulty/resource_temporal_overlap/auction_room_half_open_overlap
    """
    create_auction_session(room="ROOM-XT", scheduled_start="2026-04-05T10:00:00Z",
                           scheduled_end="2026-04-05T12:00:00Z")
    res = api.create_auction_session(
        {"room": "ROOM-XT", "scheduled_start": "2026-04-05T12:00:00Z",
         "scheduled_end": "2026-04-05T14:00:00Z"}, SALES)
    validate_success(res, 201)


# ─── Rule 8b: appraiser closed-interval adjacency collision ───────────────

def test_appraiser_touching_boundary_collides(api):
    """PRD §3.8: "these intervals are treated as closed on both ends, so an
    appointment that touches another exactly at its boundary (one ending at the
    instant the next begins) is treated as a collision and rejected with
    ERR_APPRAISER_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/appraiser_closed_interval_adjacency_collision
    """
    appraiser = validate_success(
        api.create_appraiser({"name": "Grader Ann", "specialty_metal": "GOLD"}, SALES), 201)
    customer = create_customer("Owner A")
    cons1 = create_intake_consignment(customer["id"], reserve_price_cents=10_000, description="Coin A")
    cons2 = create_intake_consignment(customer["id"], reserve_price_cents=10_000, description="Coin B")

    validate_success(api.create_appraisal_appointment(
        {"appraiser_id": appraiser["id"], "consignment_id": cons1["id"],
         "start_at": "2026-04-06T10:00:00Z", "end_at": "2026-04-06T12:00:00Z"}, SALES), 201)

    res = api.create_appraisal_appointment(
        {"appraiser_id": appraiser["id"], "consignment_id": cons2["id"],
         "start_at": "2026-04-06T12:00:00Z", "end_at": "2026-04-06T13:00:00Z"}, SALES)
    validate_error(res, "ERR_APPRAISER_DOUBLE_BOOKED")


def test_appraiser_non_overlapping_allowed(api):
    """PRD §3.8: "A new appointment must not overlap an existing BOOKED appointment
    for the same appraiser; these intervals are treated as closed on both ends".

    Design: Difficulty/resource_temporal_overlap/appraiser_closed_interval_adjacency_collision
    """
    appraiser = validate_success(
        api.create_appraiser({"name": "Grader Bob", "specialty_metal": "GOLD"}, SALES), 201)
    customer = create_customer("Owner B")
    cons1 = create_intake_consignment(customer["id"], reserve_price_cents=10_000, description="Coin C")
    cons2 = create_intake_consignment(customer["id"], reserve_price_cents=10_000, description="Coin D")

    validate_success(api.create_appraisal_appointment(
        {"appraiser_id": appraiser["id"], "consignment_id": cons1["id"],
         "start_at": "2026-04-07T10:00:00Z", "end_at": "2026-04-07T12:00:00Z"}, SALES), 201)
    res = api.create_appraisal_appointment(
        {"appraiser_id": appraiser["id"], "consignment_id": cons2["id"],
         "start_at": "2026-04-07T13:00:00Z", "end_at": "2026-04-07T14:00:00Z"}, SALES)
    validate_success(res, 201)
