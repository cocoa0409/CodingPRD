"""Every declared calculation, implemented exactly as the PRD pins it."""
from datetime import timedelta
from decimal import Decimal

from core import db, dec, dec_ceil, rhu, rhu_int

# --- quote_pricing --------------------------------------------------------
SCRAP_ALLOWANCE_PCT = dec("0.02")
MACHINE_ATTENDED_RATE_CENTS_PER_HOUR = dec(9500)
MACHINE_LIGHTS_OUT_RATE_CENTS_PER_HOUR = dec(6200)
SETUP_RATE_CENTS_PER_HOUR = dec(11000)
SECONDARY_RATE_CENTS_PER_HOUR = dec(7400)
LIGHTS_OUT_MAX_FRACTION = dec("0.60")
MATERIAL_MARKUP_PCT = dec("0.18")
MARGIN_PCT = dec("0.22")
PART_OFF_KERF_MM = dec("2.0")
SETUP_SCRAP_LENGTH_MM = dec(300)
QUOTE_VALID_UNTIL_DAYS = 30

# --- blanket_po_rebate ----------------------------------------------------
REBATE_TIER_1_MIN_CENTS = 500000
REBATE_TIER_2_MIN_CENTS = 2000000
REBATE_TIER_3_MIN_CENTS = 10000000
REBATE_TIER_0_PCT = dec("0.00")
REBATE_TIER_1_PCT = dec("0.03")
REBATE_TIER_2_PCT = dec("0.06")
REBATE_TIER_3_PCT = dec("0.09")

# --- bar_length_ledger ----------------------------------------------------
BAR_REMNANT_MM = dec(150)

# --- capability_index -----------------------------------------------------
D2_BY_SUBGROUP_SIZE = {3: dec("1.693"), 5: dec("2.326")}
PPK_MIN_ACCEPT = dec("1.00")
CPK_MIN_DEFAULT = dec("1.33")

# --- tool_wear_state ------------------------------------------------------
OFFSET_DRIFT_LIMIT_UM_DEFAULT = dec(8)

# --- chip_and_coolant_accrual --------------------------------------------
COOLANT_LITERS_PER_MACHINE_HOUR = dec("0.35")

# --- reclamation_credit ---------------------------------------------------
ALLOY_SCRAP_RATE_CENTS_PER_KG = {
    "303SS": dec(118),
    "316SS": dec(132),
    "C360": dec(465),
    "6061AL": dec(87),
    "12L14": dec(41),
}
COOLANT_COST_CENTS_PER_LITER = dec(420)

# --- machine_window_occupancy --------------------------------------------
CHANGEOVER_BUFFER_MINUTES = 45

# --- gauge thresholds -----------------------------------------------------
GRR_MAX_PCT = dec(10)
GRR_RETIRE_PCT = dec(30)

ALLOY_CODES = ("303SS", "316SS", "C360", "6061AL", "12L14")
GAUGE_TYPES = ("MICROMETER", "BORE_GAUGE", "OPTICAL_COMPARATOR", "CMM")
CERTIFICATIONS = ("SWISS_SETUP", "LIGHTS_OUT", "CMM", "DEBURR")
OPERATIONS = ("DEBURR", "WASH", "HEAT_TREAT", "PLATING", "INSPECTION_100PCT")


# ==========================================================================
# quote_pricing
# ==========================================================================
def price_quote(quote, part, costing_basis):
    lot_qty = dec(quote["lot_qty"])
    effective_qty = dec_ceil(lot_qty * (dec(1) + SCRAP_ALLOWANCE_PCT))

    if costing_basis == "HISTORICAL_CYCLE" and part.get("observed_avg_cycle_time_sec") is not None:
        cycle_time_used = dec(part["observed_avg_cycle_time_sec"])
    else:
        cycle_time_used = dec(part["cycle_time_sec"])

    run_hours = (dec(effective_qty) * cycle_time_used) / dec(3600)

    if not part.get("lights_out_eligible"):
        lights_out_hours = dec(0)
    else:
        requested = dec(quote.get("requested_lights_out_hours") or 0)
        cap = run_hours * LIGHTS_OUT_MAX_FRACTION
        lights_out_hours = requested if requested < cap else cap
    attended_hours = run_hours - lights_out_hours

    run_cost_cents = rhu_int(attended_hours * MACHINE_ATTENDED_RATE_CENTS_PER_HOUR) + \
        rhu_int(lights_out_hours * MACHINE_LIGHTS_OUT_RATE_CENTS_PER_HOUR)
    setup_cost_cents = rhu_int(dec(part["setup_hours"]) * SETUP_RATE_CENTS_PER_HOUR)
    if part.get("secondary_required"):
        secondary_cost_cents = rhu_int(
            lot_qty * dec(part.get("secondary_minutes_per_piece") or 0) / dec(60)
            * SECONDARY_RATE_CENTS_PER_HOUR)
    else:
        secondary_cost_cents = 0

    bar_length_required_mm = dec(effective_qty) * (dec(part["cut_off_length_mm"]) + PART_OFF_KERF_MM) \
        + SETUP_SCRAP_LENGTH_MM
    material_cost_cents = rhu_int(
        bar_length_required_mm / dec(1000)
        * dec(part["material_cost_cents_per_meter"])
        * (dec(1) + MATERIAL_MARKUP_PCT))

    quoted_lot_cost_cents = run_cost_cents + setup_cost_cents + secondary_cost_cents + material_cost_cents
    quoted_unit_price_cents = rhu_int(dec(quoted_lot_cost_cents) / lot_qty / (dec(1) - MARGIN_PCT))

    return {
        "costing_basis": costing_basis,
        "cycle_time_used_sec": cycle_time_used,
        "effective_qty": effective_qty,
        "run_cost_cents": run_cost_cents,
        "setup_cost_cents": setup_cost_cents,
        "secondary_cost_cents": secondary_cost_cents,
        "material_cost_cents": material_cost_cents,
        "quoted_lot_cost_cents": quoted_lot_cost_cents,
        "quoted_unit_price_cents": quoted_unit_price_cents,
    }


# ==========================================================================
# blanket_po_rebate
# ==========================================================================
def blanket_rebate(list_unit_price_cents, total_committed_qty):
    pre_rebate_total_cents = int(list_unit_price_cents) * int(total_committed_qty)
    if pre_rebate_total_cents < REBATE_TIER_1_MIN_CENTS:
        rebate_pct = REBATE_TIER_0_PCT
    elif pre_rebate_total_cents < REBATE_TIER_2_MIN_CENTS:
        rebate_pct = REBATE_TIER_1_PCT
    elif pre_rebate_total_cents < REBATE_TIER_3_MIN_CENTS:
        rebate_pct = REBATE_TIER_2_PCT
    else:
        rebate_pct = REBATE_TIER_3_PCT
    net_unit_price_cents = rhu_int(dec(list_unit_price_cents) * (dec(1) - rebate_pct))
    committed_value_cents = net_unit_price_cents * int(total_committed_qty)
    return {
        "list_unit_price_cents": int(list_unit_price_cents),
        "pre_rebate_total_cents": pre_rebate_total_cents,
        "rebate_pct": rebate_pct,
        "net_unit_price_cents": net_unit_price_cents,
        "committed_value_cents": committed_value_cents,
    }


# ==========================================================================
# bar_length_ledger — reservation arithmetic
# ==========================================================================
def reservation(part, lot, qty_ordered):
    required_length_mm = dec(qty_ordered) * (dec(part["cut_off_length_mm"]) + PART_OFF_KERF_MM) \
        + SETUP_SCRAP_LENGTH_MM
    usable_length_per_bar_mm = dec(lot["bar_length_mm"]) - BAR_REMNANT_MM
    if usable_length_per_bar_mm <= 0:
        bars_reserved = 0
    else:
        bars_reserved = dec_ceil(required_length_mm / usable_length_per_bar_mm)
    reserved_length_mm = dec(bars_reserved) * dec(lot["bar_length_mm"])
    return required_length_mm, bars_reserved, reserved_length_mm


# ==========================================================================
# capability_index — cpk_short_term (one subgroup)
# ==========================================================================
def subgroup_stats(measurements, characteristic):
    count = dec(len(measurements))
    total = sum(measurements, dec(0))
    mean_s = total / count
    range_s = max(measurements) - min(measurements)
    d2 = D2_BY_SUBGROUP_SIZE.get(int(characteristic["subgroup_size"]), dec("2.326"))
    sigma_within = range_s / d2

    usl = dec(characteristic["usl"])
    lsl = dec(characteristic["lsl"])
    upper = usl - mean_s
    lower = mean_s - lsl
    nearest = upper if upper < lower else lower
    if sigma_within == 0:
        cpk = None
    else:
        cpk = rhu(nearest / (dec(3) * sigma_within), 3)

    out_of_spec_count = 0
    for value in measurements:
        if value < lsl or value > usl:
            out_of_spec_count += 1

    cpk_min = dec(characteristic.get("cpk_min", CPK_MIN_DEFAULT))
    if out_of_spec_count > 0:
        disposition = "REJECT"
    elif cpk is None or cpk >= cpk_min:
        disposition = "ACCEPT"
    else:
        disposition = "MARGINAL"

    return {
        "mean": rhu(mean_s, 4),
        "range": rhu(range_s, 4),
        "sigma_within": rhu(sigma_within, 6),
        "cpk_short_term": cpk,
        "out_of_spec_count": out_of_spec_count,
        "disposition": disposition,
    }


# ==========================================================================
# capability_index — ppk_long_term (pooled over one characteristic)
# ==========================================================================
def pooled_readings(work_order_id, characteristic_id):
    rows = [s for s in db.spc_samples.values()
            if s["work_order_id"] == work_order_id and s["characteristic_id"] == characteristic_id]
    rows.sort(key=lambda s: (s["created_at"], s["piece_index"], s["_seq"]))
    pooled = []
    for row in rows:
        pooled.extend(row["measurements"])
    return rows, pooled


def ppk_long_term(work_order_id, characteristic):
    _rows, pooled = pooled_readings(work_order_id, characteristic["id"])
    if len(pooled) < 2:
        return None
    count = dec(len(pooled))
    mean_l = sum(pooled, dec(0)) / count
    variance = sum(((x - mean_l) * (x - mean_l) for x in pooled), dec(0)) / (count - dec(1))
    if variance <= 0:
        return None
    s_overall = variance.sqrt()
    usl = dec(characteristic["usl"])
    lsl = dec(characteristic["lsl"])
    upper = usl - mean_l
    lower = mean_l - lsl
    nearest = upper if upper < lower else lower
    return rhu(nearest / (dec(3) * s_overall), 3)


# ==========================================================================
# spc_sampling_requirement
# ==========================================================================
def characteristics_of(part_id):
    rows = [c for c in db.characteristics.values() if c["part_id"] == part_id]
    rows.sort(key=lambda c: (c["created_at"], c["_seq"]))
    return rows


def samples_of(work_order_id, characteristic_id=None):
    rows = [s for s in db.spc_samples.values() if s["work_order_id"] == work_order_id]
    if characteristic_id is not None:
        rows = [s for s in rows if s["characteristic_id"] == characteristic_id]
    rows.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return rows


def sampling_summary(work_order, characteristic_id=None):
    chars = characteristics_of(work_order["part_id"])
    if characteristic_id is not None:
        chars = [c for c in chars if c["id"] == characteristic_id]

    required_sample_count = 0
    sample_count = 0
    complete = True
    ppk_values = []
    for char in chars:
        required_c = dec_ceil(dec(work_order["qty_ordered"]) / dec(char["sample_freq_pieces"]))
        actual = samples_of(work_order["id"], char["id"])
        actual_c = len(actual)
        required_sample_count += required_c
        sample_count += actual_c
        if actual_c < required_c:
            complete = False
        if actual_c >= 2:
            value = ppk_long_term(work_order["id"], char)
            if value is not None:
                ppk_values.append(value)

    all_samples = samples_of(work_order["id"], characteristic_id)
    out_of_spec_count = sum(int(s["out_of_spec_count"]) for s in all_samples)
    cpk_values = [s["cpk_short_term"] for s in all_samples if s["cpk_short_term"] is not None]

    return {
        "work_order_id": work_order["id"],
        "characteristic_count": len(chars),
        "sample_count": sample_count,
        "required_sample_count": required_sample_count,
        "out_of_spec_count": out_of_spec_count,
        "cpk_short_term_min": min(cpk_values) if cpk_values else None,
        "ppk_long_term_min": min(ppk_values) if ppk_values else None,
        "_complete": complete,
        "_ppk_values": ppk_values,
    }


# ==========================================================================
# observed_cycle_time
# ==========================================================================
def recompute_observed_cycle_time(part):
    accepted = [w for w in db.work_orders.values()
                if w["part_id"] == part["id"] and w["quality_status"] == "ACCEPTED"]
    total_good = sum(int(w.get("qty_good") or 0) for w in accepted)
    part["observed_accepted_qty"] = total_good
    if total_good == 0:
        part["observed_avg_cycle_time_sec"] = None
    else:
        total_seconds = sum((dec(w.get("actual_run_seconds") or 0) for w in accepted), dec(0))
        part["observed_avg_cycle_time_sec"] = rhu(total_seconds / dec(total_good), 1)


# ==========================================================================
# tool_wear_state
# ==========================================================================
def tool_wear_state(station):
    if int(station["pieces_since_index"]) >= int(station["expected_life_pieces"]):
        return "LIFE_EXPIRED"
    if abs(dec(station["cumulative_drift_um"])) >= dec(station["drift_limit_um"]):
        return "OFFSET_HOLD"
    return "IN_SERVICE"


# ==========================================================================
# chip_and_coolant_accrual
# ==========================================================================
def chip_and_coolant(work_order, lot, part, machine):
    consumed_meters = dec(work_order["reserved_length_mm"]) / dec(1000)
    chip_kg = rhu(consumed_meters * dec(lot["mass_kg_per_meter"])
                  - dec(work_order["qty_good"]) * dec(part["finished_mass_g"]) / dec(1000), 3)
    alloy = part["alloy_code"]
    existing = machine["chip_accrual_by_alloy"].get(alloy, dec(0))
    machine["chip_accrual_by_alloy"][alloy] = rhu(dec(existing) + chip_kg, 3)
    machine["coolant_makeup_liters"] = rhu(
        dec(machine["coolant_makeup_liters"])
        + (dec(work_order["actual_run_seconds"]) / dec(3600)) * COOLANT_LITERS_PER_MACHINE_HOUR, 3)
    return chip_kg


# ==========================================================================
# reclamation_credit
# ==========================================================================
def reclamation_credit(machine):
    chip_credit_cents = 0
    for alloy in sorted(machine["chip_accrual_by_alloy"].keys()):
        kilograms = dec(machine["chip_accrual_by_alloy"][alloy])
        if kilograms == 0:
            continue
        rate = ALLOY_SCRAP_RATE_CENTS_PER_KG.get(alloy, dec(0))
        chip_credit_cents += rhu_int(kilograms * rate)
    coolant_cost_cents = rhu_int(dec(machine["coolant_makeup_liters"]) * COOLANT_COST_CENTS_PER_LITER)
    return chip_credit_cents - coolant_cost_cents


# ==========================================================================
# machine_window_occupancy  (half-open, conditional changeover buffer)
# ==========================================================================
def machine_window_conflict(machine_id, candidate_start, candidate_end, candidate_part):
    existing = [w for w in db.work_orders.values()
                if w["machine_id"] == machine_id and w["machining_status"] != "CANCELLED"]
    existing.sort(key=lambda w: (w["_start_dt"], w["created_at"], w["_seq"]))
    candidate_diameter = dec(candidate_part["bar_diameter_mm"])
    for job in existing:
        job_part = db.parts.get(job["part_id"])
        if job_part is not None and dec(job_part["bar_diameter_mm"]) == candidate_diameter:
            buffer_minutes = 0
        else:
            buffer_minutes = CHANGEOVER_BUFFER_MINUTES
        buffered_end = job["_end_dt"] + timedelta(minutes=buffer_minutes)
        if candidate_start < buffered_end and job["_start_dt"] < candidate_end:
            return True
    return False


# ==========================================================================
# bar_lot_feeder_occupancy  (closed intervals, aggregate capacity)
# ==========================================================================
def bar_lot_feeder_conflict(lot, candidate_start, candidate_end):
    overlapping = 0
    for job in db.work_orders.values():
        if job["bar_lot_id"] != lot["id"] or job["machining_status"] == "CANCELLED":
            continue
        if candidate_start <= job["_end_dt"] and job["_start_dt"] <= candidate_end:
            overlapping += 1
    return (overlapping + 1) > int(lot["feeder_slots"])
