"""Calculation rules (scaffold section 1.3): effective cavitation, cycle
throughput, AQL sampling, freight-of-air, logistics comparison, resin
reconciliation, purge quantity. All money in integer cents; weights via
Decimal with ROUND_HALF_UP per the pinned rounding orders."""
import math
from decimal import Decimal, ROUND_HALF_UP

# --- throughput constants ---
BASE_CYCLE_S = Decimal("10.0")
WEIGHT_COEFF_S_PER_G = Decimal("0.08")
LABELER_CAP_CPH = Decimal("240")
YIELD_FRACTION = Decimal("0.97")

# --- freight constants ---
DIM_DIVISOR_CM3_PER_KG = Decimal("6000")
PALLET_CUBE_CM3 = 144000
PALLET_TARE_KG = Decimal("20")
BOTTLES_PER_PALLET = 1500
PREFORMS_PER_PALLET = 30000
TRUCK_CUBE_CM3 = Decimal("96000000")
TRUCK_PAYLOAD_KG = Decimal("24000")
ONSITE_FEE_CENTS_PER_BOTTLE = 40

VARIANCE_TOLERANCE_PCT = Decimal("3.0")

MIN_EFFECTIVE_CAVITIES = 1

PURGE_MATRIX = {
    "CLEAR": {"CLEAR": Decimal("0.0"), "LIGHT": Decimal("1.0"), "DARK": Decimal("1.0")},
    "LIGHT": {"CLEAR": Decimal("2.0"), "LIGHT": Decimal("0.0"), "DARK": Decimal("1.0")},
    "DARK": {"CLEAR": Decimal("3.0"), "LIGHT": Decimal("2.5"), "DARK": Decimal("0.0")},
}


def d2(v):
    return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def effective_cavities(base_cavities, open_blockout_count):
    eff = base_cavities - open_blockout_count
    return max(MIN_EFFECTIVE_CAVITIES, eff)


def throughput_preview(base_cavities, open_blockout_count, reference_weight_g,
                       requires_inline_labeler, has_inline_labeler,
                       planned_weight_g):
    eff = effective_cavities(base_cavities, open_blockout_count)
    over = planned_weight_g - reference_weight_g
    if over < 0:
        over = Decimal("0")
    cycle_time_s = (BASE_CYCLE_S + WEIGHT_COEFF_S_PER_G * over).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    cycles_per_hour = Decimal("3600") / cycle_time_s
    if requires_inline_labeler and has_inline_labeler:
        if cycles_per_hour > LABELER_CAP_CPH:
            cycles_per_hour = LABELER_CAP_CPH
    hourly_output = int((cycles_per_hour * eff * YIELD_FRACTION).to_integral_value(
        rounding="ROUND_FLOOR"))
    return {
        "effective_cavities": eff,
        "cycle_time_s": cycle_time_s,
        "cycles_per_hour": cycles_per_hour,
        "hourly_output": hourly_output,
    }


# AQL bands keyed on lot_size (inclusive upper bounds; None = unbounded)
AQL_BANDS = [
    (280, 20, 1, 1),
    (1200, 50, 2, 2),
    (10000, 125, 3, 4),
    (None, 200, 5, 6),
]


def aql_for(lot_size):
    for upper, n, c_leak, c_drop in AQL_BANDS:
        if upper is None or lot_size <= upper:
            return n, c_leak, c_drop
    raise AssertionError("unreachable")


def freight_compute(spec, quantity, shipment_mode, tiers):
    """Freight-of-air charge. quantity: int; tiers: cleaned tier list
    (Decimal min_kg / rate). Returns dict of computed figures."""
    if shipment_mode == "FINISHED_BOTTLES":
        units_per_pallet = BOTTLES_PER_PALLET
        unit_cube = int(spec["bottle_cube_cm3"])
        unit_weight_g = Decimal(spec["target_weight_g"])
    else:  # PREFORMS
        units_per_pallet = PREFORMS_PER_PALLET
        unit_cube = int(spec["preform_cube_cm3"])
        unit_weight_g = Decimal(spec["preform_weight_g"])

    pallets = -(-quantity // units_per_pallet)  # ceil
    full_pallets = quantity // units_per_pallet
    rem_units = quantity - full_pallets * units_per_pallet

    # PINNED: dim weight per pallet, rounded half-up to 0.1 kg, then summed
    per_full_dim = ((Decimal(units_per_pallet * unit_cube + PALLET_CUBE_CM3)
                     / DIM_DIVISOR_CM3_PER_KG)
                    .quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    if rem_units > 0:
        rem_dim = ((Decimal(rem_units * unit_cube + PALLET_CUBE_CM3)
                    / DIM_DIVISOR_CM3_PER_KG)
                   .quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    else:
        rem_dim = Decimal("0")
    dim_weight_kg = per_full_dim * full_pallets + rem_dim

    actual_weight_kg = (Decimal(quantity) * unit_weight_g / Decimal("1000")
                        + Decimal(pallets) * PALLET_TARE_KG).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    chargeable_weight_kg = max(dim_weight_kg, actual_weight_kg)

    # PINNED: marginal tiers; each tier charge rounded half-up to cents, summed
    freight_cost_cents = 0
    w = chargeable_weight_kg
    for i, tier in enumerate(tiers):
        lo = tier["min_kg"]
        hi = tiers[i + 1]["min_kg"] if i + 1 < len(tiers) else None
        upper = w if hi is None else min(w, hi)
        kg_in_tier = upper - lo
        if kg_in_tier < 0:
            kg_in_tier = Decimal("0")
        charge = (kg_in_tier * tier["rate_cents_per_kg"]).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)
        freight_cost_cents += int(charge)

    # Truck loading: capped by both cube and payload
    pallet_cube_cm3 = Decimal(units_per_pallet * unit_cube + PALLET_CUBE_CM3)
    pallet_gross_kg = (Decimal(units_per_pallet) * unit_weight_g / Decimal("1000")
                       + PALLET_TARE_KG)
    by_cube = int(TRUCK_CUBE_CM3 // pallet_cube_cm3) if pallet_cube_cm3 > 0 else 0
    by_payload = int(TRUCK_PAYLOAD_KG // pallet_gross_kg) if pallet_gross_kg > 0 else 0
    pallets_per_truck = min(by_cube, by_payload)
    if pallets_per_truck < 1:
        pallets_per_truck = 1
    trucks = -(-pallets // pallets_per_truck)

    volume_cm3 = quantity * unit_cube + pallets * PALLET_CUBE_CM3

    return {
        "pallets": pallets,
        "trucks": trucks,
        "volume_cm3": volume_cm3,
        "dim_weight_kg": dim_weight_kg,
        "actual_weight_kg": actual_weight_kg,
        "chargeable_weight_kg": chargeable_weight_kg,
        "freight_cost_cents": freight_cost_cents,
    }


def logistics_comparison(spec, quantity, tiers):
    warehouse = freight_compute(spec, quantity, "FINISHED_BOTTLES", tiers)
    onsite = freight_compute(spec, quantity, "PREFORMS", tiers)
    warehouse_total = warehouse["freight_cost_cents"]
    blow_on_site_total = (onsite["freight_cost_cents"]
                          + quantity * ONSITE_FEE_CENTS_PER_BOTTLE)
    recommended = "WAREHOUSE" if warehouse_total <= blow_on_site_total else "BLOW_ON_SITE"
    return {
        "warehouse_total_cents": warehouse_total,
        "blow_on_site_total_cents": blow_on_site_total,
        "recommended_mode": recommended,
    }


def reconciliation(cycles_completed, cavities_active_at_start, planned_weight_g,
                   actual_drawdown_kg):
    """provisional 2dp half-up; variance pct 2dp half-up; alert strictly > 3.0."""
    provisional = (Decimal(cycles_completed) * Decimal(cavities_active_at_start)
                   * Decimal(planned_weight_g) / Decimal("1000")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    if provisional == 0:
        variance_pct = Decimal("0.00")
    else:
        variance_pct = ((Decimal(actual_drawdown_kg) - provisional) / provisional
                        * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
    variance_alert = bool(variance_pct > VARIANCE_TOLERANCE_PCT)
    return provisional, variance_pct, variance_alert


def purge_kg_for(from_class, to_class, resident_volume_kg):
    if from_class is None:
        multiplier = Decimal("0.0")
    else:
        multiplier = PURGE_MATRIX[from_class][to_class]
    return (Decimal(resident_volume_kg) * multiplier).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
