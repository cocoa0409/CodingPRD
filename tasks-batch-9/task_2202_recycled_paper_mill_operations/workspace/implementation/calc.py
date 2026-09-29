"""Calculations (PRD §3). All money 2dp, tonnage 3dp, round half up."""
from decimal import Decimal

from shape import D, q

ZERO = Decimal("0")


# ------------------------------------------------ §3.1 indexed fiber price ---
FUEL_SURCHARGE_RATE = Decimal("0.185")


def volume_discount(provisional_extended):
    if provisional_extended < Decimal("100000.00"):
        return Decimal("0.000")
    if provisional_extended < Decimal("250000.00"):
        return Decimal("0.015")
    return Decimal("0.030")


def indexed_fiber_unit_price(published_price, negotiated_delta, contracted_tons, freight_per_ton):
    base = q(D(published_price) + D(negotiated_delta), 2)
    provisional_extended = q(base * D(contracted_tons), 2)
    discount = volume_discount(provisional_extended)
    fuel = q(D(freight_per_ton) * FUEL_SURCHARGE_RATE, 2)
    unit = q(base * (Decimal("1") - discount) + D(freight_per_ton) + fuel, 2)
    extended = q(unit * D(contracted_tons), 2)
    return {
        "base_price": base,
        "provisional_extended_value": provisional_extended,
        "discount": discount,
        "fuel_surcharge_per_ton": fuel,
        "quoted_unit_price_per_ton": unit,
        "extended_contract_value": extended,
    }


# ------------------------------------------------------ §3.2 receipt tonnage ---
def receipt_net_tons(sublots, max_moisture_pct):
    ceiling = D(max_moisture_pct)
    ordered = sorted(sublots, key=lambda s: s["sublot_no"])
    wet_list = []
    ded_sum = ZERO
    dry_sum = ZERO
    wmoist_num = ZERO
    wcont_num = ZERO
    wet_total = ZERO
    for s in ordered:
        wet = q(D(s["gross_tons"]) - D(s["tare_tons"]), 3)
        excess = D(s["moisture_pct"]) - ceiling
        if excess < ZERO:
            excess = ZERO
        ded = q(wet * excess / Decimal("100"), 3)
        dry = q(wet - ded, 3)
        wet_list.append(wet)
        ded_sum += ded
        dry_sum += dry
        wet_total += wet
        wmoist_num += wet * D(s["moisture_pct"])
        wcont_num += wet * D(s["contamination_pct"])
    if wet_total == ZERO:
        wm = ZERO
        wc = ZERO
    else:
        wm = q(wmoist_num / wet_total, 2)
        wc = q(wcont_num / wet_total, 2)
    return {
        "net_tons": float(q(dry_sum, 2)),
        "moisture_deduction_tons": float(q(ded_sum, 3)),
        "weighted_moisture_pct": float(wm),
        "weighted_contamination_pct": float(wc),
    }


# --------------------------------------------------------- §3.2 supplier posture ---
def supplier_qualification_posture(strike_count):
    if strike_count >= 4:
        return "SUSPENDED"
    if strike_count >= 2:
        return "PROBATION"
    return "QUALIFIED"


# ------------------------------------------------------- §3.3 pulp yield ---
YIELD_FLOOR = Decimal("45.00")
CONTAMINATION_YIELD_PENALTY = Decimal("1.8")


def blend_contamination(lines, lots_by_id, charged_tons):
    if D(charged_tons) == ZERO:
        return float(ZERO)
    num = ZERO
    for ln in lines:
        lot = lots_by_id[ln["inventory_lot_id"]]
        num += D(ln["tons_charged"]) * D(lot["contamination_pct"])
    return float(q(num / D(charged_tons), 3))


def pulp_yield_provisional(ordered_lines, lots_by_id, grades_by_code):
    total = ZERO
    for ln in ordered_lines:
        lot = lots_by_id[ln["inventory_lot_id"]]
        grade = grades_by_code[lot["grade_code"]]
        nominal = D(grade["nominal_yield_pct"])
        # §3.3: "the effective yield is the larger of 45.00 and the nominal yield
        # minus 1.8 times the lot contamination" — the contamination is not floored.
        effective = nominal - CONTAMINATION_YIELD_PENALTY * D(lot["contamination_pct"])
        if effective < YIELD_FLOOR:
            effective = YIELD_FLOOR
        total += q(D(ln["tons_charged"]) * effective / Decimal("100"), 3)
    return float(q(total, 3))


def pulp_yield_final(charged_tons, measured_reject_tons, deink_sludge_tons):
    return float(q(D(charged_tons) - D(measured_reject_tons) - D(deink_sludge_tons), 3))


# ------------------------------------------------------ §3.3 deink chemistry ---
CAUSTIC_USD_PER_KG = Decimal("0.62")
PEROXIDE_USD_PER_KG = Decimal("1.15")
SURFACTANT_USD_PER_KG = Decimal("3.40")
TISSUE_PREMIUM = Decimal("1.10")
EFFECTIVENESS_DECAY = Decimal("0.65")
BASE_REMOVAL = Decimal("0.35")
SURFACTANT_COEFF = Decimal("0.08")
MAX_REMOVAL = Decimal("0.95")
INK_LOAD_PCT = Decimal("4.50")


def deink_pass(caustic_kg, peroxide_kg, surfactant_kg, charged_tons, family, pass_index):
    raw = q(D(caustic_kg) * CAUSTIC_USD_PER_KG
            + D(peroxide_kg) * PEROXIDE_USD_PER_KG
            + D(surfactant_kg) * SURFACTANT_USD_PER_KG, 2)
    if family == "TISSUE":
        pass_cost = q(raw * TISSUE_PREMIUM, 2)
    else:
        pass_cost = raw
    effectiveness = q(EFFECTIVENESS_DECAY ** (pass_index - 1), 4)
    denom = D(charged_tons)
    if denom < Decimal("1.000"):
        denom = Decimal("1.000")
    dose = D(surfactant_kg) / denom
    removal = (BASE_REMOVAL + SURFACTANT_COEFF * dose) * effectiveness
    if removal > MAX_REMOVAL:
        removal = MAX_REMOVAL
    removal = q(removal, 4)
    sludge = q(D(charged_tons) * INK_LOAD_PCT / Decimal("100") * removal, 3)
    return {
        "raw_cost": raw,
        "pass_cost": pass_cost,
        "effectiveness": effectiveness,
        "removal_fraction": removal,
        "sludge_tons": float(sludge),
    }


# ---------------------------------------------- §3.4 grade change transition ---
WASTE_CEILING = Decimal("12.000")
BRIGHTNESS_PENALTY = Decimal("1.500")


def grade_change_transition_waste(from_spec, to_spec, machine):
    delta = abs(D(to_spec["basis_weight_gsm"]) - D(from_spec["basis_weight_gsm"]))
    if delta <= Decimal("10.0"):
        base = Decimal("0.800")
    elif delta <= Decimal("40.0"):
        base = Decimal("2.500")
    else:
        base = Decimal("5.000")
    to_b = to_spec.get("min_brightness_iso")
    from_b = from_spec.get("min_brightness_iso")
    penalty = ZERO
    if to_b is not None and (from_b is None or D(to_b) > D(from_b)):
        penalty = BRIGHTNESS_PENALTY
    family_mult = Decimal("1.00") if from_spec["family"] == to_spec["family"] else Decimal("2.20")
    dir_mult = Decimal("1.15") if int(to_spec["rank_order"]) < int(from_spec["rank_order"]) else Decimal("1.00")
    waste = (base + penalty) * family_mult * dir_mult
    if waste > WASTE_CEILING:
        waste = WASTE_CEILING
    waste = q(waste, 3)
    raw_minutes = waste / D(machine["max_tons_per_hour"]) * Decimal("60")
    ceil_minutes = int(-((-raw_minutes).to_integral_value(rounding="ROUND_FLOOR")))
    if Decimal(ceil_minutes) < raw_minutes:
        ceil_minutes += 1
    minutes = ceil_minutes + int(machine["changeover_buffer_minutes"])
    return {"transition_waste_tons": float(waste), "transition_minutes": minutes}


# --------------------------------------------------- §3.5 run quality index ---
BW_PENALTY_PER_PCT = Decimal("4.0")
MOISTURE_PENALTY_PER_PCT = Decimal("12.0")
STRENGTH_PENALTY = Decimal("30.0")
OFF_SPEC_BW_PCT = Decimal("5.00")
QUALITY_GATE = Decimal("85.00")


def reel_deviations(reel, spec):
    spec_bw = D(spec["basis_weight_gsm"])
    bw_dev = abs(D(reel["basis_weight_gsm"]) - spec_bw) / spec_bw * Decimal("100")
    m_dev = abs(D(reel["moisture_pct"]) - D(spec["target_moisture_pct"]))
    min_sct = D(spec["min_sct_kn_m"])
    if min_sct == ZERO:
        ratio = Decimal("1.0000")
    else:
        ratio = D(reel["sct_kn_m"]) / min_sct
    return bw_dev, m_dev, ratio


def reel_score(reel, spec):
    bw_dev, m_dev, ratio = reel_deviations(reel, spec)
    bw_pen = BW_PENALTY_PER_PCT * bw_dev
    over = m_dev - D(spec["moisture_tolerance_pct"])
    if over < ZERO:
        over = ZERO
    m_pen = MOISTURE_PENALTY_PER_PCT * over
    short = Decimal("1") - ratio
    if short < ZERO:
        short = ZERO
    s_pen = STRENGTH_PENALTY * short
    score = Decimal("100.00") - bw_pen - m_pen - s_pen
    if score < ZERO:
        score = ZERO
    return q(score, 2)


def is_off_spec(reel, spec):
    bw_dev, m_dev, _ = reel_deviations(reel, spec)
    if bw_dev > OFF_SPEC_BW_PCT:
        return True
    if m_dev > D(spec["moisture_tolerance_pct"]):
        return True
    if D(reel["sct_kn_m"]) < D(spec["min_sct_kn_m"]):
        return True
    return False


def off_spec_reel_count(reels, spec):
    return sum(1 for r in reels if is_off_spec(r, spec))


def run_quality_index_provisional(reels, spec):
    ordered = sorted(reels, key=lambda r: r["reel_no"])
    first = reel_score(ordered[0], spec)
    last = reel_score(ordered[-1], spec)
    return float(q((first + last) / Decimal("2"), 2))


def run_quality_index_certified(reels, spec):
    num = ZERO
    den = ZERO
    for r in reels:
        num += D(r["reel_tons"]) * reel_score(r, spec)
        den += D(r["reel_tons"])
    if den == ZERO:
        return float(ZERO)
    return float(q(num / den, 2))


# ------------------------------------------- §3.7 effluent rolling compliance ---
from datetime import date, timedelta  # noqa: E402

WATCH_RATIO = Decimal("0.90")


def _parse_date(s):
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def effluent_rolling_compliance(readings, permit):
    """readings: non-voided reading rows of the permit."""
    if not readings:
        return {
            "rolling_bod_kg_per_day": 0.0,
            "rolling_tss_kg_per_day": 0.0,
            "exceedance_day_count": 0,
            "compliance_posture": "COMPLIANT",
            "window": [],
        }
    newest = max(_parse_date(r["reading_date"]) for r in readings)
    start = newest - timedelta(days=int(permit["rolling_window_days"]) - 1)
    window = [r for r in readings if start <= _parse_date(r["reading_date"]) <= newest]
    n = Decimal(len(window))
    bod = q(sum((D(r["bod_kg"]) for r in window), ZERO) / n, 3)
    tss = q(sum((D(r["tss_kg"]) for r in window), ZERO) / n, 3)
    flow_limit = D(permit["flow_limit_m3_per_day"])
    exceed_days = sum(1 for r in window if D(r["flow_m3"]) > flow_limit)
    bod_ratio = bod / D(permit["bod_limit_kg_per_day"])
    tss_ratio = tss / D(permit["tss_limit_kg_per_day"])
    if bod_ratio > Decimal("1.00") or tss_ratio > Decimal("1.00") or exceed_days >= 2:
        posture = "EXCEEDANCE"
    elif max(bod_ratio, tss_ratio) >= WATCH_RATIO:
        posture = "WATCH"
    else:
        posture = "COMPLIANT"
    return {
        "rolling_bod_kg_per_day": float(bod),
        "rolling_tss_kg_per_day": float(tss),
        "exceedance_day_count": exceed_days,
        "compliance_posture": posture,
        "window": window,
    }


# ------------------------------------------------------- §3.8 steam header ---
HEADER_CAPACITY_TPH = Decimal("180.000")
MIN_VIABLE_TPH = Decimal("5.000")
BAND_1_TPH = Decimal("30.000")
BAND_2_TPH = Decimal("30.000")
BAND_1_RATE = Decimal("4.10")
BAND_2_RATE = Decimal("6.75")
BAND_3_RATE = Decimal("9.20")


def windows_overlap_half_open(a_start, a_end, b_start, b_end):
    return a_start < b_end and a_end > b_start


def steam_waterfall_dispatch(candidates, demand_tph):
    """candidates: overlapping GRANTED/CURTAILED rows (already ordered)."""
    consumed = q(sum((D(c["granted_tph"]) for c in candidates), ZERO), 3)
    remaining = q(HEADER_CAPACITY_TPH - consumed, 3)
    demand = D(demand_tph)
    if remaining <= ZERO:
        return {"saturated": True, "consumed": consumed, "remaining": remaining}
    if remaining >= demand:
        granted = demand
        status = "GRANTED"
    elif remaining < MIN_VIABLE_TPH:
        return {"saturated": True, "consumed": consumed, "remaining": remaining}
    else:
        granted = remaining
        status = "CURTAILED"
    return {
        "saturated": False,
        "consumed": consumed,
        "remaining": remaining,
        "granted_tph": float(q(granted, 3)),
        "curtailed_tph": float(q(demand - granted, 3)),
        "status": status,
    }


def cogen_credit(consumed, granted_tph, window_start, window_end):
    seconds = D((window_end - window_start).total_seconds())
    duration_hours = q(seconds / Decimal("3600"), 4)
    exportable = HEADER_CAPACITY_TPH - D(consumed) - D(granted_tph)
    if exportable < ZERO:
        exportable = ZERO
    exportable = q(exportable, 3)
    b1 = min(exportable, BAND_1_TPH)
    b2 = min(max(exportable - BAND_1_TPH, ZERO), BAND_2_TPH)
    b3 = max(exportable - BAND_1_TPH - BAND_2_TPH, ZERO)
    total = (q(b1 * BAND_1_RATE * duration_hours, 4)
             + q(b2 * BAND_2_RATE * duration_hours, 4)
             + q(b3 * BAND_3_RATE * duration_hours, 4))
    return float(q(total, 2))
