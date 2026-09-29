"""The nine calculations (PRD §3.2, §3.4, §3.5, §3.6, §3.7, §3.8, §3.9, §2.8, §2.9).

Every rounding is round half up at a named point (PRD §2.8).
"""

from decimal import Decimal, ROUND_HALF_UP

# --- fabrication_cost_estimate (PRD §3.7) --------------------------------
SHOP_RATE_CENTS_PER_HOUR = {
    "STANDARD": 9500,
    "PRECISION": 14500,
    "CONSERVATION_GRADE": 18500,
}
MATERIAL_RATE_CENTS_PER_M2 = {
    "CASE_INTERIOR": 42500,
    "CASE_EXTERIOR": 31000,
    "MOUNT": 58000,
    "GRAPHIC": 12500,
    "INTERACTIVE_HOUSING": 47500,
}
FINISH_PCT = {
    "MILL": "0.0",
    "SATIN": "0.075",
    "MUSEUM_GLOSS": "0.135",
}
SCHEMATIC_LABOR_MULTIPLIER = "1.15"
SCHEMATIC_WASTE_FACTOR = "1.20"
ACTUAL_LABOR_MULTIPLIER = "1.00"

# --- interactive_durability_index (PRD §3.8) -----------------------------
OPERATING_DAYS_PER_YEAR = 320
WEAR_WEIGHT = "0.55"
WEAR_CAP = "60.0"
KIND_WEIGHT = "0.9"
KIND_FRAGILITY = {
    "TOUCHSCREEN": 18,
    "MECHANICAL": 26,
    "PROJECTION": 14,
    "AUDIO": 8,
    "AR_HEADSET": 34,
}
PARTS_WEIGHT = "1.0"
PARTS_TARGET_YEARS = 10
PARTS_POINTS_PER_YEAR = 5
PROTOTYPE_CREDIT = 8
MAINTENANCE_TIER_BANDS = (("80", "LOW"), ("60", "MEDIUM"), ("40", "HIGH"))
WARRANTY_FLOOR_MONTHS = {"LOW": 12, "MEDIUM": 24, "HIGH": 36, "CRITICAL": 60}

# --- case_environmental_envelope (PRD §3.4) ------------------------------
SILICA_KG_PER_M3_PER_EXCHANGE = "3.5"
UV_CEILING = "75.0"
SECURITY_RANK = {"BASIC": 1, "ENHANCED": 2, "HIGH_VALUE": 3}

# --- package_flow_and_accessibility (PRD §3.2) ---------------------------
CIRCULATION_SQM_PER_VISITOR_HOUR = "0.65"
MIN_EGRESS_CLEAR_WIDTH_CM = 112
MIN_WHEELCHAIR_TURNING_RADIUS_CM = 76
MIN_FLOW_CAPACITY_SCORE = "60.0"

# --- material_offgassing_verdict (PRD §3.6) ------------------------------
VOC_LIMIT = {
    "CASE_INTERIOR": "0.05",
    "MOUNT": "0.05",
    "CASE_EXTERIOR": "0.50",
    "GRAPHIC": "0.80",
    "INTERACTIVE_HOUSING": "0.60",
}
FORMALDEHYDE_LIMIT = {
    "CASE_INTERIOR": "0.02",
    "MOUNT": "0.02",
    "CASE_EXTERIOR": "0.10",
    "GRAPHIC": "0.10",
    "INTERACTIVE_HOUSING": "0.10",
}
MIN_CURE_DAYS = {
    "CASE_INTERIOR": 21,
    "MOUNT": 21,
    "CASE_EXTERIOR": 7,
    "GRAPHIC": 3,
    "INTERACTIVE_HOUSING": 5,
}

# --- window geometry (PRD §3.9) -----------------------------------------
PRE_ACCESS_BUFFER_MIN = {"QUIET": 0, "NOISY": 15, "DUST_GENERATING": 30, "CRANE_ACCESS": 45}
SETTLING_BUFFER_MIN = {"QUIET": 0, "NOISY": 30, "DUST_GENERATING": 120, "CRANE_ACCESS": 60}
DEFAULT_MAX_CONCURRENT_CLOSURES = 2

# --- closeout_settlement (PRD §3.9) -------------------------------------
PARTS_PREMIUM_BANDS = ((15, "0.005"), (10, "0.012"), (5, "0.028"), (0, "0.045"))
RETAINAGE_BANDS = ((20000000, "0.05"), (5000000, "0.075"), (0, "0.10"))
WARRANTY_RESERVE_PCT = "0.02"


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu_cents(value):
    """Round half up to whole cents; returns int."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu(value, places):
    exponent = Decimal(1).scaleb(-places)
    return D(value).quantize(exponent, rounding=ROUND_HALF_UP)


# =========================================================================
# 1. fabrication_cost_estimate  (PRD §3.7)
#    Three line items, EACH rounded to whole cents BEFORE they are summed.
# =========================================================================
def fabrication_cost(complexity_tier, hours, labor_multiplier, material_area_m2,
                     material_used_in, waste_factor, finish_grade):
    shop_rate = SHOP_RATE_CENTS_PER_HOUR[complexity_tier]
    material_rate = MATERIAL_RATE_CENTS_PER_M2[material_used_in]
    labor = rhu_cents(D(hours) * D(shop_rate) * D(labor_multiplier))
    material = rhu_cents(D(material_area_m2) * D(material_rate) * D(waste_factor))
    finishing = rhu_cents(D(material) * D(FINISH_PCT[finish_grade]))
    return {
        "labor_cents": labor,
        "material_cents": material,
        "finishing_cents": finishing,
        "total_cents": labor + material + finishing,
    }


def fabrication_cost_schematic(drawing, material):
    """Variant: schematic estimate — labour multiplier 1.15, waste allowance 1.20."""
    return fabrication_cost(
        drawing["complexity_tier"], drawing["shop_hours"], SCHEMATIC_LABOR_MULTIPLIER,
        drawing["material_area_m2"], material["used_in"], SCHEMATIC_WASTE_FACTOR,
        drawing["finish_grade"],
    )


def fabrication_cost_actual(drawing, material, actual_shop_hours, actual_waste_factor):
    """Variant: shop-drawing actual — multiplier exactly 1.00, supplied waste factor."""
    return fabrication_cost(
        drawing["complexity_tier"], actual_shop_hours, ACTUAL_LABOR_MULTIPLIER,
        drawing["material_area_m2"], material["used_in"], actual_waste_factor,
        drawing["finish_grade"],
    )


# =========================================================================
# 2. interactive_durability_index  (PRD §3.8)
# =========================================================================
def durability_index(kind, daily_uses, duty_hours_per_day, mtbf_cycles, parts_availability_years,
                     prototype_credit):
    wear_ratio = (D(daily_uses) * D(duty_hours_per_day) * D(OPERATING_DAYS_PER_YEAR)) / D(mtbf_cycles)
    wear_pct = wear_ratio * D(100)
    capped = wear_pct if wear_pct < D(WEAR_CAP) else D(WEAR_CAP)
    wear_penalty = D(WEAR_WEIGHT) * capped
    kind_penalty = D(KIND_WEIGHT) * D(KIND_FRAGILITY[kind])
    shortfall = PARTS_TARGET_YEARS - int(parts_availability_years)
    if shortfall < 0:
        shortfall = 0
    parts_penalty = D(PARTS_WEIGHT) * D(shortfall) * D(PARTS_POINTS_PER_YEAR)
    raw = D(100) - wear_penalty - kind_penalty - parts_penalty + D(prototype_credit)
    if raw > D(100):
        raw = D("100.0")
    return rhu(raw, 2)


def durability_index_spec(interactive):
    return durability_index(
        interactive["kind"], interactive["expected_daily_uses"], interactive["duty_hours_per_day"],
        interactive["mtbf_cycles"], interactive["parts_availability_years"], 0,
    )


def durability_index_verified(interactive):
    return durability_index(
        interactive["kind"], interactive["measured_daily_uses"], interactive["duty_hours_per_day"],
        interactive["measured_mtbf_cycles"], interactive["parts_availability_years"],
        PROTOTYPE_CREDIT,
    )


def maintenance_tier(interactive):
    index = interactive.get("durability_index_verified", None)
    if index is None:
        index = interactive.get("durability_index_spec", None)
    if index is None:
        return None
    value = D(index)
    for threshold, tier in MAINTENANCE_TIER_BANDS:
        if value >= D(threshold):
            return tier
    return "CRITICAL"


# =========================================================================
# 3. case_environmental_envelope  (PRD §3.4) — strictest wins
# =========================================================================
def case_volume_m3(case):
    raw = (D(case["interior_l_cm"]) * D(case["interior_w_cm"]) * D(case["interior_h_cm"])) / D(1000000)
    return rhu(raw, 4)


def silica_gel_kg(case, volume):
    return rhu(D(volume) * D(case["air_exchanges_per_day"]) * D(SILICA_KG_PER_M3_PER_EXCHANGE), 2)


def case_envelope(case, artifacts):
    """artifacts: the objects currently RESERVED or PLACED in the case."""
    result = {
        "required_rh_min_pct": None,
        "required_rh_max_pct": None,
        "allowed_lux": None,
        "env_feasible": True,
        "security_ok": True,
    }
    if not artifacts:
        return result
    # Largest of the floors, smallest of the ceilings, smallest of the lux caps.
    # The raw stored numbers are kept for the response; comparisons run on Decimal.
    rh_min = max((a["required_rh_min_pct"] for a in artifacts), key=D)
    rh_max = min((a["required_rh_max_pct"] for a in artifacts), key=D)
    lux = min((a["max_lux"] for a in artifacts), key=D)
    target_rh = D(case["target_rh_pct"])
    tolerance = D(case["rh_tolerance_pct"])
    feasible = (
        D(rh_min) <= D(rh_max)
        and (target_rh - tolerance) >= D(rh_min)
        and (target_rh + tolerance) <= D(rh_max)
        and D(case["target_lux"]) <= D(lux)
        and D(case["uv_microwatt_per_lumen"]) <= D(UV_CEILING)
    )
    highest = max(SECURITY_RANK[a["security_class"]] for a in artifacts)
    result["required_rh_min_pct"] = rh_min
    result["required_rh_max_pct"] = rh_max
    result["allowed_lux"] = lux
    result["env_feasible"] = bool(feasible)
    result["security_ok"] = SECURITY_RANK[case["security_tier"]] >= highest
    return result


# =========================================================================
# 4. package_flow_and_accessibility  (PRD §3.2)
# =========================================================================
def package_flow(peak_visitors_per_hour, circulation_area_sqm, egress_clear_width_cm,
                 wheelchair_turning_radius_cm):
    required_area = D(peak_visitors_per_hour) * D(CIRCULATION_SQM_PER_VISITOR_HOUR)
    ratio = D(circulation_area_sqm) / required_area
    score = ratio * D(100)
    if score > D(100):
        score = D("100.0")
    score = rhu(score, 2)
    passes = (
        D(egress_clear_width_cm) >= D(MIN_EGRESS_CLEAR_WIDTH_CM)
        and D(wheelchair_turning_radius_cm) >= D(MIN_WHEELCHAIR_TURNING_RADIUS_CM)
        and score >= D(MIN_FLOW_CAPACITY_SCORE)
    )
    return score, bool(passes)


# =========================================================================
# 5. material_offgassing_verdict  (PRD §3.6) — the assembly decides the limits
# =========================================================================
def material_verdict(used_in, oddy_test_result, voc_mg_per_m2_day, formaldehyde_ppm, cure_days):
    voc_limit = D(VOC_LIMIT[used_in])
    ch2o_limit = D(FORMALDEHYDE_LIMIT[used_in])
    min_cure = MIN_CURE_DAYS[used_in]
    voc = D(voc_mg_per_m2_day)
    ch2o = D(formaldehyde_ppm)
    if oddy_test_result in ("FAIL", "UNTESTED") or voc > (voc_limit * D(2)) or ch2o > (ch2o_limit * D(2)):
        return "UNSAFE"
    if oddy_test_result == "PASS" and voc <= voc_limit and ch2o <= ch2o_limit and int(cure_days) >= min_cure:
        return "CONSERVATION_SAFE"
    return "CONDITIONAL_SAFE"


# =========================================================================
# 6. zone_window_conflict_geometry  (PRD §3.9) — half-open, buffered
# =========================================================================
def window_buffers(work_class, zone_dust_settling_buffer_minutes):
    pre = PRE_ACCESS_BUFFER_MIN[work_class]
    settling = SETTLING_BUFFER_MIN[work_class]
    if work_class == "DUST_GENERATING":
        zone_buffer = int(zone_dust_settling_buffer_minutes)
        if zone_buffer > settling:
            settling = zone_buffer
    return pre, settling


def effective_bounds(starts_at, ends_at, pre_minutes, settling_minutes):
    from datetime import timedelta

    return (starts_at - timedelta(minutes=pre_minutes), ends_at + timedelta(minutes=settling_minutes))


def windows_conflict(new_window, other):
    """Half-open overlap on the EFFECTIVE instants: touching edges do not conflict."""
    return (
        new_window["effective_start_at"] < other["effective_end_at"]
        and other["effective_start_at"] < new_window["effective_end_at"]
    )


# =========================================================================
# 7. project_closure_capacity_peak  (PRD §3.9) — closed interval, unbuffered
#    At an equal timestamp EVERY start is processed before EVERY end,
#    ties broken by the owning window's created_at ascending.
# =========================================================================
def closure_capacity_peak(windows):
    events = []
    for w in windows:
        events.append((w["starts_at"], 0, w["created_at"], w["_seq"], 1))
        events.append((w["ends_at"], 1, w["created_at"], w["_seq"], -1))
    events.sort(key=lambda e: (e[0], e[1], e[2], e[3]))
    running = 0
    peak = 0
    for event in events:
        running += event[4]
        if running > peak:
            peak = running
    return peak


# =========================================================================
# 8. project_readiness_posture  (PRD §2.9) — six counters, first match wins
# =========================================================================
def posture_from_counters(conservation_block_count, open_revision_count, conditional_case_count,
                          pending_material_count):
    if conservation_block_count > 0:
        return "FROZEN_CONSERVATION"
    if open_revision_count > 0 or conditional_case_count > 0 or pending_material_count > 0:
        return "RESTRICTED"
    return "OPEN"


# =========================================================================
# 9. closeout_settlement  (PRD §3.9) — pinned seven-step waterfall
# =========================================================================
def _first_band(bands, value):
    for threshold, pct in bands:
        if value >= threshold:
            return D(pct)
    return D(0)


def closeout_settlement(fabrication_total_cents, commissioned_parts_years):
    """commissioned_parts_years: parts_availability_years of every COMMISSIONED interactive."""
    # Step 1 — fabrication total (supplied by caller; integer addition).
    step1 = int(fabrication_total_cents)
    # Step 2 — parts premium: the weakest station governs the whole commission.
    if not commissioned_parts_years:
        parts_pct = D(0)
    else:
        parts_pct = _first_band(PARTS_PREMIUM_BANDS, min(commissioned_parts_years))
    step2 = rhu_cents(D(step1) * parts_pct)
    # Step 3 — pre-retainage total.
    step3 = step1 + step2
    # Step 4 — retainage percentage from the pre-retainage total.
    retainage_pct = _first_band(RETAINAGE_BANDS, step3)
    # Step 5 — retainage.
    step5 = rhu_cents(D(step3) * retainage_pct)
    # Step 6 — warranty reserve on the NET figure.
    step6 = rhu_cents(D(step3 - step5) * D(WARRANTY_RESERVE_PCT))
    # Step 7 — release by exact integer subtraction.
    step7 = step3 - step5 - step6
    return {
        "fabrication_total_cents": step1,
        "parts_premium_pct": parts_pct,
        "parts_premium_cents": step2,
        "pre_retainage_cents": step3,
        "retainage_pct": retainage_pct,
        "retainage_held_cents": step5,
        "warranty_reserve_cents": step6,
        "released_cents": step7,
    }
