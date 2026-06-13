"""Delivery price resolution and invoice computation.

Translates queue A (Difficulty) rule combinatorial_formula (CAP min + volume tier;
emergency surcharge per-line rounding) and queue B (Corner) instances from
`calculations` (MARKET tier2) and the deliver guard errors.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

AM = TEST_USERS["account_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]
DRIVER = TEST_USERS["driver_headers"]


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula — CAP base = min(cap, market) + volume tier
# ---------------------------------------------------------------------------
def test_delivery_price_cap_min_plus_volume_tier(api):
    """PRD §3.2: "For a `CAP` plan the base is the lesser of the plan's `cap_price_cents_per_gallon` and that same `ACTIVE` market quote's `market_price_cents_per_gallon"
    PRD §3.2: "if delivered gallons reach at least 300, the per-gallon discount is 12 cents; otherwise if they reach at least 150, the discount is 5 cents; below 150 gallons there is no discount. The resolved price is the base minus that discount, but never below a hard floor of 50 cents per gallon"

    Design: Difficulty/combinatorial_formula/delivery_price_cap_min_plus_volume_tier
    """
    s = fx.setup_order_on_dispatched_route(
        plan_type="CAP", cap_price=300, market_price=350,
        requested_gallons=200, region_code="NE_01", fuel_type="PROPANE",
        tank_overrides={"capacity_gallons": 600, "k_factor": 1500, "current_gallons": 100})
    delivered = fx.deliver_order(s["account"]["id"], s["order"]["id"], 200)
    # base = min(300, 350) = 300; 200 >= 150 -> tier1 disc 5 -> 295.
    assert delivered["price_cents_per_gallon"] == 295
    # invoice = 200*295 fuel (59000) + 2500 off_route (WILL_CALL) = 61500.
    assert delivered["invoice_total_cents"] == 61500


def test_delivery_price_cap_picks_market_when_below_cap(api):
    """PRD §3.2: "For a `CAP` plan the base is the lesser of the plan's `cap_price_cents_per_gallon` and that same `ACTIVE` market quote's `market_price_cents_per_gallon` — the customer pays the market rate but never more than the cap."

    Design: Difficulty/combinatorial_formula/delivery_price_cap_min_plus_volume_tier
    """
    # Market 280 is below the cap 400, so base = min(400, 280) = 280 (the market rate).
    s = fx.setup_order_on_dispatched_route(
        plan_type="CAP", cap_price=400, market_price=280,
        requested_gallons=200, region_code="NE_01", fuel_type="PROPANE",
        tank_overrides={"capacity_gallons": 600, "k_factor": 1500, "current_gallons": 100})
    delivered = fx.deliver_order(s["account"]["id"], s["order"]["id"], 200)
    # base = min(400, 280) = 280; 200 >= 150 -> tier1 disc 5 -> 275.
    assert delivered["price_cents_per_gallon"] == 275
    # invoice = 200*275 (55000) + 2500 off_route = 57500.
    assert delivered["invoice_total_cents"] == 57500


def test_delivery_price_market_volume_tier2(api):
    """PRD §3.2: "For a `MARKET` plan the base is the `market_price_cents_per_gallon` of the `ACTIVE` `MarketPrice` for the account's region and fuel."
    PRD §3.2: "if delivered gallons reach at least 300, the per-gallon discount is 12 cents"

    Design: Corner/calculations/delivery_price_market_volume_tier2
    """
    s = fx.setup_order_on_dispatched_route(
        plan_type="MARKET", market_price=350, requested_gallons=320,
        region_code="NE_01", fuel_type="PROPANE",
        tank_overrides={"capacity_gallons": 700, "k_factor": 1500, "current_gallons": 100})
    delivered = fx.deliver_order(s["account"]["id"], s["order"]["id"], 320)
    # base 350; 320 >= 300 -> tier2 disc 12 -> 338.
    assert delivered["price_cents_per_gallon"] == 338
    # invoice = 320*338 fuel (108160) + 2500 off_route = 110660.
    assert delivered["invoice_total_cents"] == 110660


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula — emergency surcharge per-line rounding
# ---------------------------------------------------------------------------
def test_invoice_total_emergency_surcharge_perline_rounding(api):
    """PRD §3.6: "If the order's `priority` is `EMERGENCY`, an emergency surcharge equal to 10 percent of that fuel line — rounded half up on its own line, before any summing — is added"
    PRD §3.6: "The `invoice_total_cents` is the sum of the fuel line, the (already-rounded) emergency surcharge, and the off-route fee. The per-line rounding order is pinned: round the surcharge line first, then sum."

    Design: Difficulty/combinatorial_formula/invoice_total_emergency_surcharge_perline_rounding
    """
    s = fx.setup_order_on_dispatched_route(
        plan_type="FIXED", locked_price=320, requested_gallons=320, priority="EMERGENCY",
        region_code="NE_01", fuel_type="PROPANE",
        tank_overrides={"capacity_gallons": 700, "k_factor": 1500, "current_gallons": 100})
    delivered = fx.deliver_order(s["account"]["id"], s["order"]["id"], 320)
    # base 320; 320 >= 300 -> tier2 disc 12 -> 308.
    assert delivered["price_cents_per_gallon"] == 308
    # fuel 320*308 = 98560; surcharge round_half_up(98560*10/100)=9856; off_route 2500.
    assert delivered["invoice_total_cents"] == 110916


def test_emergency_surcharge_added_for_emergency_order(api):
    """PRD §3.6: "If the order's `priority` is `EMERGENCY`, an emergency surcharge equal to 10 percent of that fuel line — rounded half up on its own line, before any summing — is added; a `STANDARD` order adds no surcharge."

    Design: Difficulty/combinatorial_formula/invoice_total_emergency_surcharge_perline_rounding
    """
    # STANDARD comparison: same fuel line, no surcharge.
    s = fx.setup_order_on_dispatched_route(
        plan_type="FIXED", locked_price=320, requested_gallons=320, priority="STANDARD",
        region_code="NE_01", fuel_type="PROPANE",
        tank_overrides={"capacity_gallons": 700, "k_factor": 1500, "current_gallons": 100})
    delivered = fx.deliver_order(s["account"]["id"], s["order"]["id"], 320)
    # fuel 320*308 = 98560; no surcharge; off_route 2500 -> 101060.
    assert delivered["price_cents_per_gallon"] == 308
    assert delivered["invoice_total_cents"] == 98560 + 2500


# ---------------------------------------------------------------------------
# Corner: deliver guard errors
# ---------------------------------------------------------------------------
def test_deliver_without_active_price_plan_rejected(api):
    """PRD §3.6: "the account must have an `ACTIVE` `PricePlan` (else `ERR_NO_ACTIVE_PRICE_PLAN"

    Design: Corner/validations/deliver_without_active_price_plan_rejected
    """
    s = fx.setup_order_on_dispatched_route(with_plan=False)
    account_v = fx.get_account_version(s["account"]["id"])
    resp = api.deliver_order(
        s["account"]["id"], s["order"]["id"],
        {"delivered_gallons": 200, "expected_account_version": account_v}, DRIVER)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_PRICE_PLAN.value)


def test_deliver_overfill_rejected(api):
    """PRD §3.6: "the delivered amount must be at least 1 and must not overfill the tank, meaning the tank's `current_gallons` plus `delivered_gallons` must not exceed `capacity_gallons` (else `ERR_DELIVERY_OVERFILL`)"

    Design: Corner/state_machines/deliver_overfill_rejected
    """
    s = fx.setup_order_on_dispatched_route(
        plan_type="FIXED", locked_price=300, requested_gallons=200,
        tank_overrides={"capacity_gallons": 500, "k_factor": 1500, "current_gallons": 400})
    account_v = fx.get_account_version(s["account"]["id"])
    # 400 + 200 > 500 -> overfill.
    resp = api.deliver_order(
        s["account"]["id"], s["order"]["id"],
        {"delivered_gallons": 200, "expected_account_version": account_v}, DRIVER)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_OVERFILL.value)


def test_deliver_route_not_dispatched_rejected(api):
    """PRD §3.6: "the parent route must be `DISPATCHED` (else `ERR_ROUTE_NOT_DISPATCHED`)"

    Design: Corner/errors/deliver_route_not_dispatched_rejected
    """
    s = fx.setup_order_scheduled_on_planning_route(
        plan_type="FIXED", locked_price=300, requested_gallons=200)
    account_v = fx.get_account_version(s["account"]["id"])
    resp = api.deliver_order(
        s["account"]["id"], s["order"]["id"],
        {"delivered_gallons": 200, "expected_account_version": account_v}, DRIVER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_DISPATCHED.value)
