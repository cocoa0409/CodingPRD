"""Cost calculations (PRD 3.8 / calculations assignment_fulfillment_cost and
order_cost_per_order_comparison)."""
from constants import (
    DC_BASE_CENTS_BY_ZONE, DC_PER_UNIT_CENTS, DUNNAGE_CENTS_PER_UNIT,
    NETWORK_FEE_TIER_1_LIMIT, NETWORK_FEE_TIER_1_RATE, NETWORK_FEE_TIER_2_LIMIT,
    NETWORK_FEE_TIER_2_RATE, NETWORK_FEE_TIER_3_RATE, PACKAGE_BASE_CENTS,
    REROUTE_OVERHEAD_CENTS, SERVICE_MULTIPLIER, SPLIT_PENALTY_CENTS,
    WEIGHT_STEP_CENTS, WEIGHT_STEP_GRAMS, ZONE_BASE_CENTS,
)
from db import db
from util import D, ceil_int, div, rhu_int


def zone_delta(order, store):
    return abs(order["destination_zone"] - store["origin_zone"])


def ship_cost_cents(order, store, line_units):
    """Per-line rounding then sum, lines walked ascending OrderLine.created_at."""
    base = ZONE_BASE_CENTS[zone_delta(order, store)]
    multiplier = D(SERVICE_MULTIPLIER[order["service_level"]])
    total = 0
    for order_line, units in line_units:
        sku = db.skus[order_line["sku_id"]]
        weight = sku["unit_weight_grams"] * units
        steps = ceil_int(div(weight, WEIGHT_STEP_GRAMS))
        raw = base + WEIGHT_STEP_CENTS * steps
        total += rhu_int(D(raw) * multiplier)
    return total


def component_cost(order, store, line_units, labor_minutes_charged, units_charged,
                   package_type):
    labor = ceil_int(D(labor_minutes_charged) * D(store["labor_rate_cents_per_minute"]))
    package = PACKAGE_BASE_CENTS[package_type] + DUNNAGE_CENTS_PER_UNIT * units_charged
    ship = ship_cost_cents(order, store, line_units)
    return labor + package + ship


def provisional_labor_minutes(store, assigned_units):
    return (D(store["labor_standard_minutes_per_order"])
            + D(store["pick_labor_minutes_per_unit"]) * D(assigned_units))


def dc_baseline_cents(destination_zone, total_units):
    return DC_BASE_CENTS_BY_ZONE[destination_zone] + DC_PER_UNIT_CENTS * total_units


def network_fee_rate(pre_fee_subtotal_cents):
    if pre_fee_subtotal_cents < NETWORK_FEE_TIER_1_LIMIT:
        return D(NETWORK_FEE_TIER_1_RATE)
    if pre_fee_subtotal_cents < NETWORK_FEE_TIER_2_LIMIT:
        return D(NETWORK_FEE_TIER_2_RATE)
    return D(NETWORK_FEE_TIER_3_RATE)


def order_cost_breakdown(order, component_cents, parcel_count, reroute_attempt_count,
                         total_units=None, variant="PROVISIONAL"):
    component_sum = sum(component_cents)
    split_penalty = SPLIT_PENALTY_CENTS * max(0, parcel_count - 1)
    reroute_overhead = REROUTE_OVERHEAD_CENTS * reroute_attempt_count
    pre_fee = component_sum + split_penalty + reroute_overhead
    rate = network_fee_rate(pre_fee)
    fee = rhu_int(D(pre_fee) * rate)
    store_cost = pre_fee + fee
    units = order["total_units"] if total_units is None else total_units
    dc_baseline = dc_baseline_cents(order["destination_zone"], units)
    if dc_baseline == 0:
        index = 0
    else:
        index = rhu_int(div(store_cost * 10000, dc_baseline))
    return {
        "variant": variant,
        "parcel_count": parcel_count,
        "component_sum_cents": component_sum,
        "split_penalty_cents": split_penalty,
        "reroute_overhead_cents": reroute_overhead,
        "pre_fee_subtotal_cents": pre_fee,
        "network_fee_rate": float(rate),
        "network_fee_cents": fee,
        "store_cost_cents": store_cost,
        "dc_baseline_cost_cents": dc_baseline,
        "cost_index_bps": index,
        "savings_vs_dc_cents": dc_baseline - store_cost,
    }
