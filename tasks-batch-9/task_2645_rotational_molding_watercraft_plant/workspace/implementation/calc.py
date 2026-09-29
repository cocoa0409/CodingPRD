"""Every declared calculation, with the mandated rounding order.

Money is integer cents; masses 3dp, cube 4dp, percentages / wall readings 2dp,
oven temperature 1dp, nest factors 4dp, indices 3dp.  Every intermediate a
later step reads is rounded before that step runs.
"""
from datetime import timedelta
from decimal import Decimal

from core import (S, ZERO, cents, clock_date, dsqrt, floor_int, q2, q3, q4, now)

SIZE_RANK = {"COMPACT": 1, "MID": 2, "TANDEM": 3, "OVERSIZE": 4}

# warpage index
OVEN_TEMP_REFERENCE_C = Decimal("288")
OVEN_TEMP_SPAN_C = Decimal("40")
IDEAL_ROTATION_RATIO = Decimal("4.000")
W_THERMAL = Decimal("0.40")
W_COOLING = Decimal("0.35")
W_ROTATION = Decimal("0.25")
W_DISTRIBUTION = Decimal("0.50")
WARPAGE_FLOOR = Decimal("0.000")
WARPAGE_CEILING = Decimal("5.000")
SIZE_CLASS_WARPAGE_FACTOR = {
    "COMPACT": Decimal("0.850"), "MID": Decimal("1.000"),
    "TANDEM": Decimal("1.150"), "OVERSIZE": Decimal("1.400"),
}
COOLING_MODE_WARPAGE_FACTOR = {
    "AMBIENT": Decimal("1.000"), "FORCED_AIR": Decimal("0.900"),
    "WATER_MIST": Decimal("1.250"),
}

# verdict ladder
WARPAGE_SCRAP_THRESHOLD = Decimal("2.500")
WARPAGE_REWORK_THRESHOLD = Decimal("1.200")
MAX_REWORK_COUNT = 2
MIN_MEASUREMENT_POINTS = 6

# order cost
OVERHEAD_TIERS = ((500000, Decimal("18.00")), (2000000, Decimal("14.50")))
OVERHEAD_TOP_RATE_PCT = Decimal("11.00")

# freight
DIM_FACTOR_KG_PER_M3 = Decimal("120.000")
ZONE_RATE_CENTS_PER_KG = {"Z1": Decimal("42"), "Z2": Decimal("61"), "Z3": Decimal("88")}
UTILIZATION_DISCOUNT_TIERS = (
    (Decimal("90.00"), Decimal("12.00")),
    (Decimal("75.00"), Decimal("7.50")),
    (Decimal("60.00"), Decimal("3.00")),
)
FUEL_SURCHARGE_PCT = Decimal("9.50")
MIN_SEAL_UTILIZATION_PCT = Decimal("60.00")

# warranty
WARRANTY_TERM_MONTHS = 60
CLAIM_TYPE_FACTOR = {
    "HULL_DEFORMATION": Decimal("1.00"), "HARDWARE": Decimal("0.60"),
    "COSMETIC": Decimal("0.30"),
}
FLAT_SCHEDULE_BANDS = ((12, Decimal("80.00")), (36, Decimal("50.00")), (60, Decimal("25.00")))
ADMIN_FEE_TIERS = ((50000, Decimal("12.00")), (200000, Decimal("8.00")))
ADMIN_FEE_TOP_RATE_PCT = Decimal("5.00")
STORAGE_WAIVED_DEDUCTION_PCT = Decimal("35.00")
DEFORMATION_THRESHOLD_MM = Decimal("3.00")
OVERBUILD_FACTOR = Decimal("1.20")

ACTIVE_CYCLE_STATES = ("SCHEDULED", "OVEN_RUNNING", "COOLING")
OCCUPYING_LOGISTICS = ("STORED", "LOADED")


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------
def model_of_cycle(cycle):
    order = S.production_orders.get(cycle["production_order_id"])
    return S.product_models.get(order["product_model_id"]) if order else None


def cycles_of_order(order):
    return [c for c in S.molding_cycles.values()
            if c["production_order_id"] == order["id"]]


def charges_of_cycle(cycle):
    return [c for c in S.resin_charges.values()
            if c["molding_cycle_id"] == cycle["id"]]


def units_of_order(order):
    ids = set(c["id"] for c in cycles_of_order(order))
    return [u for u in S.finished_units.values() if u["molding_cycle_id"] in ids]


def units_of_warehouse(warehouse_id):
    return [u for u in S.finished_units.values() if u.get("warehouse_id") == warehouse_id]


def lines_of_shipment(shipment_id, status=None):
    out = [l for l in S.shipment_lines.values() if l["shipment_id"] == shipment_id]
    if status:
        out = [l for l in out if l["status"] == status]
    return out


# --------------------------------------------------------------------------
# resin lot qualification
# --------------------------------------------------------------------------
def min_shot_mass_kg(model):
    return q3(model["nominal_charge_kg"] * (Decimal(1) - model["charge_tolerance_pct"] / Decimal(100)))


def lot_qualifies(lot, model):
    if lot["status"] != "AVAILABLE":
        return False
    if lot["resin_grade"] != model["resin_grade"]:
        return False
    if lot["additive_package_code"] != model["required_additive_package_code"]:
        return False
    if not (lot["color_code"] == model["master_color_code"]
            or lot["color_delta_e"] <= model["max_color_delta_e"]):
        return False
    if not (model["min_melt_index_g10min"] <= lot["melt_index_g10min"]
            <= model["max_melt_index_g10min"]):
        return False
    if lot["regrind_pct_by_mass"] > model["max_regrind_pct"]:
        return False
    if lot["expires_on"] < clock_date():
        return False
    if lot["available_kg"] < min_shot_mass_kg(model):
        return False
    return True


def qualified_lot_count(model):
    return sum(1 for lot in S.resin_lots.values() if lot_qualifies(lot, model))


def melt_index_in_band(model, value):
    return model["min_melt_index_g10min"] <= value <= model["max_melt_index_g10min"]


# --------------------------------------------------------------------------
# cycle charge roll-ups
# --------------------------------------------------------------------------
def cycle_rollups(cycle):
    participating = [c for c in charges_of_cycle(cycle)
                     if c["status"] in ("RESERVED", "CONSUMED")]
    charged = q3(sum((c["charge_kg"] for c in participating), ZERO))
    if charged == q3(ZERO):
        return q3(ZERO), None, q2(ZERO)
    numerator = ZERO
    for c in participating:
        lot = S.resin_lots.get(c["resin_lot_id"])
        numerator += c["charge_kg"] * lot["melt_index_g10min"]
    weighted = q2(numerator / charged)
    total_regrind = q3(sum((c["regrind_kg"] for c in participating), ZERO))
    total_charge = q3(sum((c["charge_kg"] for c in participating), ZERO))
    regrind_pct = q2(ZERO) if total_charge == q3(ZERO) else q2(
        total_regrind / total_charge * Decimal(100))
    return charged, weighted, regrind_pct


def blended_regrind_pct(charges):
    total_regrind = q3(sum((c["regrind_kg"] for c in charges), ZERO))
    total_charge = q3(sum((c["charge_kg"] for c in charges), ZERO))
    if total_charge == q3(ZERO):
        return q2(ZERO)
    return q2(total_regrind / total_charge * Decimal(100))


# --------------------------------------------------------------------------
# wall thickness distribution
# --------------------------------------------------------------------------
def wall_distribution(points):
    n = len(points)
    mean = q3(sum(points, ZERO) / Decimal(n))
    acc = ZERO
    for p in points:
        diff = p - mean
        acc += diff * diff
    sd = dsqrt(acc / Decimal(n), 3)
    cv = q2(ZERO) if mean == q3(ZERO) else q2(sd / mean * Decimal(100))
    return mean, sd, cv, q3(min(points))


# --------------------------------------------------------------------------
# warpage index (PROVISIONAL at demould, FINAL at inspection)
# --------------------------------------------------------------------------
def warpage_index(model, cycle, variant, wall_cv_pct=None):
    thermal = q3(abs(cycle["oven_temp_c"] - OVEN_TEMP_REFERENCE_C) / OVEN_TEMP_SPAN_C)
    min_cool = Decimal(model["min_cooling_minutes"])
    if variant == "PROVISIONAL":
        applied_cooling = Decimal(cycle["scheduled_cooling_minutes"])
    else:
        applied_cooling = Decimal(cycle["actual_cooling_minutes"])
    deficit = min_cool - applied_cooling
    if deficit < 0:
        deficit = ZERO
    cooling = q3(deficit / min_cool)
    ratio = q3(cycle["arm_rpm_major"] / cycle["arm_rpm_minor"])
    rotation = q3(abs(ratio - IDEAL_ROTATION_RATIO) / IDEAL_ROTATION_RATIO)
    if variant == "PROVISIONAL" or wall_cv_pct is None:
        distribution = q3(ZERO)
    else:
        over = wall_cv_pct - model["wall_cv_max_pct"]
        if over < 0:
            over = ZERO
        distribution = q3(over / Decimal(10))
    base = q3(W_THERMAL * thermal + W_COOLING * cooling
              + W_ROTATION * rotation + W_DISTRIBUTION * distribution)
    product = (base * SIZE_CLASS_WARPAGE_FACTOR[model["size_class"]]
               * COOLING_MODE_WARPAGE_FACTOR[cycle["cooling_mode"]])
    if product < WARPAGE_FLOOR:
        product = WARPAGE_FLOOR
    if product > WARPAGE_CEILING:
        product = WARPAGE_CEILING
    return q3(product)


# --------------------------------------------------------------------------
# inspection verdict ladder
# --------------------------------------------------------------------------
def inspection_verdict(model, unit):
    verdict = None
    if unit["min_wall_thickness_mm"] < model["wall_thickness_min_mm"]:
        verdict = "SCRAP"
    elif unit["impact_test_joules"] < model["impact_test_min_joules"]:
        verdict = "SCRAP"
    elif unit["cosmetic_defect_grade"] == "REJECT":
        verdict = "SCRAP"
    elif unit["final_warpage_index"] > WARPAGE_SCRAP_THRESHOLD:
        verdict = "SCRAP"
    elif unit["wall_cv_pct"] > model["wall_cv_max_pct"]:
        verdict = "REWORK"
    elif unit["final_warpage_index"] > WARPAGE_REWORK_THRESHOLD:
        verdict = "REWORK"
    elif unit["cosmetic_defect_grade"] == "C":
        verdict = "REWORK"
    else:
        verdict = "PASS"
    if verdict == "REWORK" and unit["rework_count"] >= MAX_REWORK_COUNT:
        verdict = "SCRAP"
    return verdict


# --------------------------------------------------------------------------
# production order cost
# --------------------------------------------------------------------------
def order_cost(order):
    cycles = cycles_of_order(order)
    cycle_ids = set(c["id"] for c in cycles)
    consumed = [c for c in S.resin_charges.values()
                if c["molding_cycle_id"] in cycle_ids and c["status"] == "CONSUMED"]
    material = 0
    for charge in consumed:
        lot = S.resin_lots.get(charge["resin_lot_id"])
        material += cents(charge["charge_kg"] * Decimal(lot["cost_cents_per_kg"]))
    demolded = [c for c in cycles if c["status"] == "DEMOLDED"]
    energy = 0
    for cycle in demolded:
        station = S.oven_stations.get(cycle["oven_station_id"])
        energy += cents(Decimal(cycle["actual_oven_minutes"])
                        * Decimal(station["energy_cents_per_min"]))
    subtotal = material + energy
    rate = OVERHEAD_TOP_RATE_PCT
    for ceiling, tier_rate in OVERHEAD_TIERS:
        if subtotal <= ceiling:
            rate = tier_rate
            break
    overhead = cents(Decimal(subtotal) * rate / Decimal(100))
    total = subtotal + overhead
    completed = order["completed_qty"]
    unit_cost = None
    if completed >= 1:
        unit_cost = floor_int(Decimal(total) / Decimal(completed))
    return {
        "consumed_charge_count": len(consumed),
        "material_cost_cents": material,
        "demolded_cycle_count": len(demolded),
        "oven_energy_cost_cents": energy,
        "pre_overhead_subtotal_cents": subtotal,
        "overhead_rate_pct": rate,
        "overhead_cents": overhead,
        "total_cost_cents": total,
        "completed_qty": completed,
        "unit_cost_cents": unit_cost,
    }


def order_completion(order):
    units = units_of_order(order)
    completed = sum(
        1 for u in units
        if u["build_status"] == "SELLABLE"
        or u["logistics_status"] in ("STORED", "LOADED", "IN_TRANSIT", "DELIVERED"))
    scrapped = sum(1 for u in units if u["build_status"] == "SCRAPPED")
    return completed, scrapped


def overbuild_ceiling(order):
    return floor_int(Decimal(order["ordered_qty"]) * OVERBUILD_FACTOR)


# --------------------------------------------------------------------------
# Interval arithmetic.  THREE DISTINCT SEMANTICS - never unified.
#   oven arm    : exclusive per arm, half-open span, symmetric changeover
#                 buffer applied to the STORED cycle only.
#   cooling bay : aggregate slot capacity, CLOSED span, no buffer.
#   mould       : exclusive over the combined oven+cooling span, half-open.
# --------------------------------------------------------------------------
def overlaps_half_open(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def overlaps_closed(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def project_windows(oven_start_at, oven_minutes, cooling_minutes):
    oven_end = oven_start_at + timedelta(minutes=oven_minutes)
    cool_start = oven_end
    cool_end = cool_start + timedelta(minutes=cooling_minutes)
    return oven_end, cool_start, cool_end


def oven_arm_conflicts(station, arm_index, cand_start, cand_end, exclude_id=None):
    buffer_min = timedelta(minutes=station["changeover_buffer_min"])
    hits = []
    for cycle in S.molding_cycles.values():
        if exclude_id and cycle["id"] == exclude_id:
            continue
        if cycle["oven_station_id"] != station["id"]:
            continue
        if cycle["arm_index"] != arm_index:
            continue
        if cycle["status"] not in ("SCHEDULED", "OVEN_RUNNING"):
            continue
        stored_start = cycle["oven_start_at"] - buffer_min
        stored_end = cycle["oven_end_at"] + buffer_min
        if overlaps_half_open(cand_start, cand_end, stored_start, stored_end):
            hits.append(cycle)
    return hits


def cooling_bay_intersecting(bay, cand_start, cand_end, exclude_id=None):
    hits = []
    for cycle in S.molding_cycles.values():
        if exclude_id and cycle["id"] == exclude_id:
            continue
        if cycle["cooling_bay_id"] != bay["id"]:
            continue
        if cycle["status"] not in ACTIVE_CYCLE_STATES:
            continue
        if overlaps_closed(cand_start, cand_end,
                           cycle["cooling_window_start_at"],
                           cycle["cooling_window_end_at"]):
            hits.append(cycle)
    return hits


def mold_occupied(mold_id, cand_start, cand_end, exclude_id=None):
    for cycle in S.molding_cycles.values():
        if exclude_id and cycle["id"] == exclude_id:
            continue
        if cycle.get("mold_id") != mold_id:
            continue
        if cycle["status"] not in ACTIVE_CYCLE_STATES:
            continue
        if overlaps_half_open(cand_start, cand_end,
                              cycle["oven_start_at"], cycle["cooling_window_end_at"]):
            return True
    return False


# --------------------------------------------------------------------------
# mould selection
# --------------------------------------------------------------------------
def select_mold(order, station, cand_start, cand_end, exclude_ids):
    same_model = [m for m in S.molds.values()
                  if m["product_model_id"] == order["product_model_id"]]
    available = [m for m in same_model if m["status"] == "AVAILABLE"]
    station_rank = SIZE_RANK[station["max_size_class"]]
    eligible = []
    removed_by_overlap = False
    for mold in available:
        if SIZE_RANK[mold["size_class"]] > station_rank:
            continue
        if mold["cycles_since_service"] >= mold["service_interval_cycles"]:
            continue
        if mold_occupied(mold["id"], cand_start, cand_end):
            removed_by_overlap = True
            continue
        eligible.append(mold)
    excluded = set(exclude_ids or [])
    pool = [m for m in eligible if m["id"] not in excluded]
    if not pool:
        if not eligible and available and removed_by_overlap:
            return None, "ERR_MOLD_WINDOW_CONFLICT"
        return None, "ERR_NO_ELIGIBLE_MOLD"
    pool.sort(key=lambda m: (m["cycles_since_service"], m["mold_code"]))
    return pool[0], None


# --------------------------------------------------------------------------
# warehouse zone selection, footprint and posture
# --------------------------------------------------------------------------
def occupying_units(warehouse_id):
    return [u for u in S.finished_units.values()
            if u.get("warehouse_id") == warehouse_id
            and u["logistics_status"] in OCCUPYING_LOGISTICS]


def zone_committed_cube(warehouse_id, zone_code):
    total = ZERO
    for u in occupying_units(warehouse_id):
        if u.get("storage_zone_code") == zone_code:
            total += u["stored_footprint_cube_m3"]
    return q4(total)


def zone_anchor_exists(warehouse_id, zone_code, product_model_id):
    for u in occupying_units(warehouse_id):
        if (u.get("storage_zone_code") == zone_code
                and u["product_model_id"] == product_model_id
                and u.get("is_zone_anchor")):
            return True
    return False


def select_zone(warehouse, model):
    candidates = []
    for zone in warehouse["zones"]:
        code = zone["zone_code"]
        anchor = zone_anchor_exists(warehouse["id"], code, model["id"])
        if anchor:
            footprint = q4(model["gross_cube_m3"] * model["nest_factor"])
        else:
            footprint = q4(model["gross_cube_m3"])
        committed = zone_committed_cube(warehouse["id"], code)
        remaining = q4(zone["capacity_cube_m3"] - committed - footprint)
        if remaining < q4(ZERO):
            continue
        candidates.append({
            "zone_code": code,
            "anchor_exists": anchor,
            "footprint": footprint,
            "remaining_after": remaining,
        })
    if not candidates:
        return None
    candidates.sort(key=lambda c: (0 if c["anchor_exists"] else 1,
                                   c["remaining_after"], c["zone_code"]))
    return candidates[0]


def warehouse_committed_cube(warehouse):
    total = ZERO
    for u in occupying_units(warehouse["id"]):
        total += u["stored_footprint_cube_m3"]
    return q4(total)


def derive_posture(utilization_pct, warehouse):
    if utilization_pct >= warehouse["frozen_threshold_pct"]:
        return "FROZEN"
    if utilization_pct >= warehouse["restricted_threshold_pct"]:
        return "RESTRICTED"
    return "NORMAL"


def build_ahead_cap_qty(bucket):
    return floor_int(Decimal(bucket["forecast_qty"]) * bucket["build_ahead_cap_pct"]
                     / Decimal(100))


def build_ahead_committed_qty(bucket):
    return sum(1 for u in S.finished_units.values()
               if u.get("demand_bucket_id") == bucket["id"]
               and u["build_status"] == "SELLABLE"
               and u["logistics_status"] in OCCUPYING_LOGISTICS)


# --------------------------------------------------------------------------
# trailer cube roll-up and freight
# --------------------------------------------------------------------------
def ordered_loaded_lines(shipment_id):
    lines = lines_of_shipment(shipment_id, "LOADED")

    def key(line):
        unit = S.finished_units.get(line["finished_unit_id"])
        return (line["created_at"], unit["hull_serial"] if unit else "")

    return sorted(lines, key=key)


def shipment_rollup(shipment):
    """Recomputed from scratch on every line addition and removal."""
    lines = ordered_loaded_lines(shipment["id"])
    seen_models = {}
    loaded_cube = ZERO
    nested_cube = ZERO
    weight = ZERO
    for line in lines:
        unit = S.finished_units.get(line["finished_unit_id"])
        model = S.product_models.get(unit["product_model_id"])
        position = 1 + seen_models.get(model["id"], 0)
        seen_models[model["id"]] = position
        gross = q4(model["gross_cube_m3"])
        nested = gross if position == 1 else q4(model["gross_cube_m3"] * model["nest_factor"])
        line["nest_position"] = position
        line["line_gross_cube_m3"] = gross
        line["line_nested_cube_m3"] = nested
        loaded_cube += gross
        nested_cube += nested
        weight += model["unit_weight_kg"]
    shipment["loaded_cube_m3"] = q4(loaded_cube)
    shipment["nested_cube_m3"] = q4(nested_cube)
    shipment["loaded_weight_kg"] = q3(weight)
    capacity = shipment["trailer_cube_capacity_m3"]
    shipment["cube_utilization_pct"] = q2(shipment["nested_cube_m3"] / capacity * Decimal(100))
    if shipment["nested_cube_m3"] == q4(ZERO):
        shipment["density_kg_per_m3"] = q3(ZERO)
    else:
        shipment["density_kg_per_m3"] = q3(shipment["loaded_weight_kg"]
                                          / shipment["nested_cube_m3"])
    for line in lines:
        line["line_freight_cents"] = _line_freight(
            line, shipment["destination_zone"], line["line_nested_cube_m3"])
    return lines


def _line_freight(line, destination_zone, billable_cube):
    unit = S.finished_units.get(line["finished_unit_id"])
    model = S.product_models.get(unit["product_model_id"])
    dim_weight = q3(billable_cube * DIM_FACTOR_KG_PER_M3)
    chargeable = max(model["unit_weight_kg"], dim_weight)
    return cents(chargeable * ZONE_RATE_CENTS_PER_KG[destination_zone])


def chargeable_kg(line, billable_cube):
    unit = S.finished_units.get(line["finished_unit_id"])
    model = S.product_models.get(unit["product_model_id"])
    dim_weight = q3(billable_cube * DIM_FACTOR_KG_PER_M3)
    return max(model["unit_weight_kg"], dim_weight)


def discount_rate_pct(utilization_pct):
    for min_util, rate in UTILIZATION_DISCOUNT_TIERS:
        if min_util <= utilization_pct:
            return rate
    return q2(ZERO)


def shipment_freight(shipment, variant):
    """QUOTED bills each line on its nested cube, BILLED on its gross cube."""
    lines = ordered_loaded_lines(shipment["id"])
    pre_discount = 0
    per_line = []
    for line in lines:
        basis = (line["line_nested_cube_m3"] if variant == "QUOTED"
                 else line["line_gross_cube_m3"])
        amount = _line_freight(line, shipment["destination_zone"], basis)
        per_line.append((line, amount))
        pre_discount += amount
    rate = discount_rate_pct(shipment["cube_utilization_pct"])
    discount = cents(Decimal(pre_discount) * rate / Decimal(100))
    after = pre_discount - discount
    fuel = cents(Decimal(after) * FUEL_SURCHARGE_PCT / Decimal(100))
    return {
        "lines": per_line,
        "pre_discount_cents": pre_discount,
        "discount_rate_pct": rate,
        "discount_cents": discount,
        "fuel_cents": fuel,
        "freight_cents": after + fuel,
    }


# --------------------------------------------------------------------------
# warranty
# --------------------------------------------------------------------------
def months_in_service(delivered_at, current):
    if delivered_at is None:
        return 0
    months = (current.year - delivered_at.year) * 12 + (current.month - delivered_at.month)
    # The final month only counts once the day-and-time of the month has been
    # reached: twelve months and twenty-nine days is 12, never 13.
    if (current.day, current.hour, current.minute, current.second,
            current.microsecond) < (delivered_at.day, delivered_at.hour,
                                    delivered_at.minute, delivered_at.second,
                                    delivered_at.microsecond):
        months -= 1
    return max(0, months)


def coverage_pct(model, months):
    if model["warranty_basis"] == "PRO_RATA_AGE":
        remaining = Decimal(WARRANTY_TERM_MONTHS - months)
        if remaining < 0:
            remaining = ZERO
        return q2(remaining / Decimal(WARRANTY_TERM_MONTHS) * Decimal(100))
    for max_months, pct in FLAT_SCHEDULE_BANDS:
        if months <= max_months:
            return q2(pct)
    return q2(ZERO)


def warranty_payout(model, claim):
    months = claim["months_in_service"] or 0
    coverage = coverage_pct(model, months)
    factor = CLAIM_TYPE_FACTOR[claim["claim_type"]]
    gross = cents(Decimal(model["msrp_cents"]) * coverage / Decimal(100) * factor)
    fee_rate = ADMIN_FEE_TOP_RATE_PCT
    for ceiling, rate in ADMIN_FEE_TIERS:
        if gross <= ceiling:
            fee_rate = rate
            break
    admin_fee = cents(Decimal(gross) * fee_rate / Decimal(100))
    if claim["storage_review_status"] == "WAIVED":
        deduction = cents(Decimal(gross) * STORAGE_WAIVED_DEDUCTION_PCT / Decimal(100))
    else:
        deduction = 0
    net = gross - deduction - admin_fee
    if net < 0:
        net = 0
    return {
        "payout_basis": model["warranty_basis"],
        "coverage_pct": coverage,
        "pre_fee_gross_cents": gross,
        "admin_fee_rate_pct": fee_rate,
        "admin_fee_cents": admin_fee,
        "storage_deduction_cents": deduction,
        "net_payout_cents": net,
    }
