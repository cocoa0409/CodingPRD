"""Vendor settlement: per-line commission rounding and optimistic concurrency on Farm.version.

Difficulty instance: combinatorial_formula (settlement, mode b — per-line rounding).
Corner instance: optimistic-concurrency stale-version rejection.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_admin_headers,
    set_clock, new_farm, new_hub, new_customer, new_product, new_weight_product,
    new_cycle, new_offering, open_cycle, new_order, new_line, do_checkout, do_pack,
    do_fulfill, cutoff_cycle, settle_cycle, observed_farm_version, do_settlement,
    assert_settlement,
)


def _farm(api, farm_id):
    return api.get_farm(farm_id, make_admin_headers()).json()["data"]


# ---------------------------------------------------------------------------
# combinatorial_formula / settlement_commission_per_line_rounding_mode_b
# ---------------------------------------------------------------------------
def _settle_ready_two_weight_lines(api):
    """Farm (commission 0.15) with a WEIGHT product priced 2020/kg; two lines each packed at
    0.5 kg -> final 1010 each; order fulfilled; cycle SETTLED. Ready for settlement create."""
    set_clock(api)
    farm = new_farm(api, name="Sun Farm", commission_pct=0.15, snap_authorized=False)
    hub = new_hub(api)
    customer = new_customer(api, snap_balance_cents=0)
    corn = new_weight_product(api, farm["id"], name="Sweet Corn", category="PRODUCE",
                              price_per_kg_cents=2020, estimated_weight_kg=0.6, snap_eligible=False)
    cycle = new_cycle(api)
    offering = new_offering(api, cycle["id"], farm["id"], corn["id"], offered_qty=100)
    open_cycle(api, cycle["id"])
    order = new_order(api, customer["id"], cycle["id"], hub["id"])
    line1 = new_line(api, customer["id"], order["id"], offering["id"], 1)
    line2 = new_line(api, customer["id"], order["id"], offering["id"], 1)
    do_checkout(api, customer["id"], order["id"])
    cutoff_cycle(api, cycle["id"])
    do_pack(api, farm["id"], line1["id"], fulfilled_qty=1, actual_weight_kg=0.5)
    do_pack(api, farm["id"], line2["id"], fulfilled_qty=1, actual_weight_kg=0.5)
    do_fulfill(api, order["id"])
    settle_cycle(api, cycle["id"])
    return {"farm": farm, "cycle": cycle}


def test_settlement_commission_rounded_per_line(api):
    """PRD §3.9: "`commission_cents` is computed per line and then summed: for each fulfilled
    line, multiply its `final_line_cents` by the farm's `commission_pct` and round half up to
    whole cents, then add those per-line commissions together — this per-line rounding is
    deliberate and can differ by a cent or more from rounding a single combined product."
    PRD §3.9: "`gross_sales_cents` is the sum of `final_line_cents` across the farm's fulfilled
    lines in the cycle."
    PRD §3.9: "`net_payout_cents` is `gross_sales_cents` minus `commission_cents`."

    Design: Difficulty/combinatorial_formula/settlement_commission_per_line_rounding_mode_b
    """
    world = _settle_ready_two_weight_lines(api)
    version = observed_farm_version(api, world["farm"]["id"])
    resp = do_settlement(api, world["farm"]["id"], world["cycle"]["id"], version)
    data = validate_success(resp, 201)
    assert_settlement(data)
    assert data["gross_sales_cents"] == 2020
    # round(1010*0.15)=round(151.5)=152 per line; 152+152=304 (sum-then-round would be 303)
    assert data["commission_cents"] == 304
    assert data["net_payout_cents"] == 1716
    assert data["line_count"] == 2


def test_settlement_posts_payout_and_bumps_farm_version(api):
    """PRD §3.9: "Finalizing the settlement posts its `net_payout_cents` into the farm's
    `payout_balance_cents`, increments the farm's `settled_cycle_count` by 1, and increments the
    farm's `version` by 1 — which is exactly why a second create carrying a stale
    `expected_farm_version` is rejected with `ERR_STALE_FARM_VERSION`."

    Design: Difficulty/combinatorial_formula/settlement_commission_per_line_rounding_mode_b
    """
    world = _settle_ready_two_weight_lines(api)
    before = observed_farm_version(api, world["farm"]["id"])
    validate_success(do_settlement(api, world["farm"]["id"], world["cycle"]["id"], before), 201)
    farm_after = _farm(api, world["farm"]["id"])
    assert farm_after["payout_balance_cents"] == 1716
    assert farm_after["settled_cycle_count"] == 1
    assert farm_after["version"] == before + 1


# ---------------------------------------------------------------------------
# Corner: cross_cutting / settlement_create_stale_farm_version_rejected
# ---------------------------------------------------------------------------
def test_second_settlement_with_stale_version_rejected(api):
    """PRD §2.9: "The settlement-create request must carry `expected_farm_version`, a non-optional
    field holding the `version` of the target `Farm` that the client last observed."
    PRD §2.9: "if a client's `expected_farm_version` no longer equals the farm's current
    `version`, the client is working from a payout-balance view taken before some earlier
    settlement posted. Such a request is rejected with `ERR_STALE_FARM_VERSION` (HTTP 412) to
    prevent double-posting a payout onto a stale balance."

    Design: Corner/cross_cutting_complexity_layers/settlement_create_stale_farm_version_rejected
    """
    set_clock(api)
    farm = new_farm(api, name="Sun Farm", commission_pct=0.15, snap_authorized=False)
    hub = new_hub(api)
    customer = new_customer(api, snap_balance_cents=0)
    potato = new_product(api, farm["id"], name="Potatoes", category="PRODUCE", pricing_mode="FIXED",
                         unit_price_cents=400, snap_eligible=False)
    cycle = new_cycle(api)
    offering = new_offering(api, cycle["id"], farm["id"], potato["id"], offered_qty=100)
    open_cycle(api, cycle["id"])
    order = new_order(api, customer["id"], cycle["id"], hub["id"])
    line = new_line(api, customer["id"], order["id"], offering["id"], 2)
    do_checkout(api, customer["id"], order["id"])
    cutoff_cycle(api, cycle["id"])
    do_pack(api, farm["id"], line["id"], fulfilled_qty=2)
    do_fulfill(api, order["id"])
    settle_cycle(api, cycle["id"])

    version = observed_farm_version(api, farm["id"])
    first = do_settlement(api, farm["id"], cycle["id"], version)
    validate_success(first, 201)  # first create succeeds and bumps Farm.version
    second = do_settlement(api, farm["id"], cycle["id"], version)  # same (now stale) version
    validate_error(second, ApiErrorId.ERR_STALE_FARM_VERSION.value, 412)
