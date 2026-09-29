"""Every calculation rule of scaffold section 1.3 / PRD section 3.

All arithmetic that feeds a rounded or monetary result runs on Decimal, and
every rounding step is ROUND_HALF_UP as mandated by PRD section 2.9.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

# ----------------------------------------------------------------- constants
VB_LIMIT_UM = Decimal("300")

REQUIRED_LIFE_MIN = {
    "ROUGHING": Decimal("12.0"),
    "MEDIUM": Decimal("18.0"),
    "FINISHING": Decimal("25.0"),
}
MAX_RA_UM = {
    "ROUGHING": Decimal("3.2"),
    "MEDIUM": Decimal("1.6"),
    "FINISHING": Decimal("0.8"),
}
LIFE_WEIGHT = Decimal("0.6")
FINISH_WEIGHT = Decimal("0.4")
SUBSCORE_CAP = Decimal("2.0")
MIN_COMPOSITE_SCORE = Decimal("1.00")
MIN_QUALIFIED_GROUPS = 2

MIN_SINTER_DENSITY_GCC = Decimal("14.35")
HARDNESS_TOLERANCE_HV = 75
MIN_YIELD_PCT = Decimal("85.00")

CATALOG_BASE_DAYS = 5
SPECIAL_BASE_DAYS = 15
UNRELEASED_GEOMETRY_DAYS = 8
PVD_COATING_DAYS = 4
CVD_COATING_DAYS = 7
UNQUALIFIED_GRADE_DAYS = 6
EXPEDITE_ELIGIBLE_MAX_DAYS = 21
EXPEDITE_SHAVE_DAYS = 3
MIN_LEAD_DAYS = 2
SPECIAL_REVIEW_DAYS = 5

EXOTIC_GRADE_SURCHARGE_PCT = Decimal("0.08")
PVD_SURCHARGE_PCT = Decimal("0.06")
CVD_SURCHARGE_PCT = Decimal("0.10")
SPECIAL_SURCHARGE_PCT = Decimal("0.18")
VOLUME_TIERS = [(500, Decimal("0.12")), (100, Decimal("0.07")), (25, Decimal("0.03"))]

BASE_VC_M_MIN = {
    "P": Decimal("220"),
    "M": Decimal("170"),
    "K": Decimal("150"),
    "N": Decimal("400"),
    "S": Decimal("60"),
    "H": Decimal("45"),
}
MAX_VC_BY_CLASS = {
    "ROUGHING": Decimal("260"),
    "MEDIUM": Decimal("340"),
    "FINISHING": Decimal("420"),
}
MAX_FZ_BY_CLASS = {
    "ROUGHING": Decimal("0.55"),
    "MEDIUM": Decimal("0.30"),
    "FINISHING": Decimal("0.14"),
}
AP_BY_CLASS = {
    "ROUGHING": Decimal("6.0"),
    "MEDIUM": Decimal("3.0"),
    "FINISHING": Decimal("1.0"),
}
FZ_NOSE_FRACTION = Decimal("0.35")
GRADE_FACTOR_FLOOR = Decimal("0.85")
GRADE_FACTOR_CEILING = Decimal("1.20")
COATING_FACTOR_CEILING = Decimal("1.35")
RIGIDITY_FACTOR = {
    "RIGID": Decimal("1.00"),
    "MEDIUM": Decimal("0.85"),
    "WEAK": Decimal("0.70"),
}

PASS_EXTENSION_PCT = Decimal("35.0")
PASS_DECAY = Decimal("0.7")
REBATE_BASIS_CENTS = Decimal("900")
RECONDITION_COST_CENTS_PER_TOOL = 1850

DRESS_THRESHOLD_UNITS = 150
MAX_DRESS_COUNT = 3

MAX_VALIDATED_HF_CLASS = 2
THICKNESS_TOLERANCE_FRACTION = Decimal("0.15")

CHAMBER_AREA_CAPACITY_CM2 = Decimal("4000.00")
CELL_SETUP_BUFFER_MIN = 45

IT6_MAX_UM = Decimal("5.0")
IT7_MAX_UM = Decimal("12.0")
IT8_MAX_UM = Decimal("25.0")


# ----------------------------------------------------------------- primitives
def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places):
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def num(value, places):
    """Rounded Decimal rendered as a JSON number."""
    if value is None:
        return None
    return float(round_half_up(value, places))


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


# ----------------------------------------------------------------- trial life
def trial_tool_life_rating(wear):
    """Returns (rated_life_min, projected_life_min, censored) as Decimals/bool."""
    pts = [(D(e["minutes"]), D(e["vb_um"])) for e in wear]

    rated = None
    censored = False
    for i in range(len(pts) - 1):
        m_i, vb_i = pts[i]
        m_j, vb_j = pts[i + 1]
        if vb_i < VB_LIMIT_UM <= vb_j:
            rated = round_half_up(
                m_i + (VB_LIMIT_UM - vb_i) * (m_j - m_i) / (vb_j - vb_i), 1
            )
            break
    if rated is None:
        rated = round_half_up(pts[-1][0], 1)
        censored = True

    m_prev, vb_prev = pts[-2]
    m_last, vb_last = pts[-1]
    rate = (vb_last - vb_prev) / (m_last - m_prev)
    projected = round_half_up(m_last + (VB_LIMIT_UM - vb_last) / rate, 1)
    return rated, projected, censored


def trial_verdict(application_class, rated_life_min, censored, ra_um):
    if censored:
        return "FAIL"
    if rated_life_min is None or ra_um is None:
        return "FAIL"
    if D(rated_life_min) < REQUIRED_LIFE_MIN[application_class]:
        return "FAIL"
    if D(ra_um) > MAX_RA_UM[application_class]:
        return "FAIL"
    return "PASS"


def trial_subscore(application_class, rated_life_min, ra_um):
    life_ratio = min(SUBSCORE_CAP, D(rated_life_min) / REQUIRED_LIFE_MIN[application_class])
    finish_ratio = min(SUBSCORE_CAP, MAX_RA_UM[application_class] / D(ra_um))
    return round_half_up(LIFE_WEIGHT * life_ratio + FINISH_WEIGHT * finish_ratio, 2)


def dossier_composite_score(application_class, considered_trials):
    """considered_trials: COMPLETED trials ordered by created_at ascending."""
    if not considered_trials:
        return None
    total = Decimal("0")
    for t in considered_trials:
        total += trial_subscore(application_class, t["rated_life_min"],
                               t["measured_surface_ra_um"])
    return round_half_up(total / Decimal(len(considered_trials)), 2)


def product_tool_life_index(source_trials):
    if not source_trials:
        return None, []
    total = Decimal("0")
    groups = set()
    for t in source_trials:
        total += D(t["rated_life_min"])
        groups.add(t["workpiece_group"])
    index = round_half_up(total / Decimal(len(source_trials)), 1)
    return index, sorted(groups)


# ----------------------------------------------------------------- sintering
def sinter_qc_evaluation(pressed_units, sintered_units, density, hardness, target_hardness):
    yield_pct = round_half_up(Decimal(100) * Decimal(sintered_units) / Decimal(pressed_units), 2)
    ok = (
        D(density) >= MIN_SINTER_DENSITY_GCC
        and abs(int(hardness) - int(target_hardness)) <= HARDNESS_TOLERANCE_HV
        and yield_pct >= MIN_YIELD_PCT
    )
    return yield_pct, ("PASSED" if ok else "FAILED")


# ----------------------------------------------------------------- lead time
def engineering_lead_time_days(order_class, geometry_status, coating_recipe,
                               grade_status):
    base_days = CATALOG_BASE_DAYS if order_class == "CATALOG" else SPECIAL_BASE_DAYS
    geometry_days = 0 if geometry_status == "RELEASED" else UNRELEASED_GEOMETRY_DAYS
    if coating_recipe is None:
        coating_days = 0
    else:
        coating_days = (
            PVD_COATING_DAYS if coating_recipe["deposition_type"] == "PVD" else CVD_COATING_DAYS
        )
    grade_days = 0 if grade_status == "QUALIFIED" else UNQUALIFIED_GRADE_DAYS
    raw_lead_days = base_days + geometry_days + coating_days + grade_days
    expedite_eligible = raw_lead_days <= EXPEDITE_ELIGIBLE_MAX_DAYS
    shaved = raw_lead_days - EXPEDITE_SHAVE_DAYS if expedite_eligible else raw_lead_days
    return max(shaved, MIN_LEAD_DAYS), expedite_eligible


# ----------------------------------------------------------------- pricing
def order_price(list_price_cents, quantity, order_class, target_workpiece_group,
                coating_recipe):
    grade_surcharge = (
        Decimal("0.00")
        if target_workpiece_group in ("P", "M", "K")
        else EXOTIC_GRADE_SURCHARGE_PCT
    )
    if coating_recipe is None:
        coating_surcharge = Decimal("0.00")
    else:
        coating_surcharge = (
            PVD_SURCHARGE_PCT if coating_recipe["deposition_type"] == "PVD" else CVD_SURCHARGE_PCT
        )
    special_surcharge = Decimal("0.00") if order_class == "CATALOG" else SPECIAL_SURCHARGE_PCT

    volume_discount = Decimal("0.00")
    for min_qty, pct in VOLUME_TIERS:
        if quantity >= min_qty:
            volume_discount = pct
            break

    per_unit_gross = Decimal(list_price_cents) * (
        Decimal(1) + grade_surcharge + coating_surcharge + special_surcharge
    )
    per_unit_net = int(round_half_up(per_unit_gross * (Decimal(1) - volume_discount), 0))
    return per_unit_net, per_unit_net * quantity


# ----------------------------------------------------------------- speeds/feeds
def speeds_feeds_envelope(workpiece_group, machine_rigidity, coolant,
                          co_binder_pct, coating_recipe, application_class,
                          nose_radius_mm, max_depth_of_cut_mm,
                          qualified_workpiece_groups, release_status):
    grade_factor = clamp(
        Decimal("1.00") + Decimal("0.02") * (Decimal("10.0") - D(co_binder_pct)),
        GRADE_FACTOR_FLOOR,
        GRADE_FACTOR_CEILING,
    )
    if coating_recipe is None:
        coating_factor = Decimal("1.00")
    else:
        coating_factor = min(
            COATING_FACTOR_CEILING,
            Decimal("1.10") + Decimal("0.02") * D(coating_recipe["total_thickness_um"]),
        )
    rigidity_factor = RIGIDITY_FACTOR[machine_rigidity]
    if coolant == "DRY":
        coolant_factor = Decimal("0.60") if coating_recipe is None else Decimal("0.75")
    elif coolant == "FLOOD":
        coolant_factor = Decimal("1.00")
    else:
        coolant_factor = Decimal("1.10")

    vc_raw = (
        BASE_VC_M_MIN[workpiece_group]
        * grade_factor
        * coating_factor
        * rigidity_factor
        * coolant_factor
    )
    recommended_vc = int(round_half_up(min(vc_raw, MAX_VC_BY_CLASS[application_class]), 0))
    recommended_fz = round_half_up(
        min(D(nose_radius_mm) * FZ_NOSE_FRACTION, MAX_FZ_BY_CLASS[application_class]), 3
    )
    recommended_ap = round_half_up(
        min(D(max_depth_of_cut_mm), AP_BY_CLASS[application_class]), 2
    )
    if workpiece_group in (qualified_workpiece_groups or []):
        confidence = "HIGH"
    elif release_status == "RELEASED":
        confidence = "MEDIUM"
    else:
        confidence = "LOW"
    return recommended_vc, float(recommended_fz), float(recommended_ap), confidence


# ----------------------------------------------------------------- reconditioning
def recondition_life_extension(measured_length_mm, min_regrind_length_mm,
                               regrind_step_mm, nominal_length_mm, regrind_pass_no):
    remaining = (
        (D(measured_length_mm) - D(min_regrind_length_mm)) / D(regrind_step_mm)
    ).to_integral_value(rounding=ROUND_FLOOR)
    remaining_regrinds = int(remaining)
    if remaining_regrinds < 0:
        remaining_regrinds = 0
    life_extension_pct = round_half_up(
        Decimal(100) * Decimal(remaining_regrinds) * D(regrind_step_mm) / D(nominal_length_mm), 1
    )
    scrap_recommended = D(measured_length_mm) < D(min_regrind_length_mm)
    warranted = round_half_up(
        PASS_EXTENSION_PCT * (PASS_DECAY ** (int(regrind_pass_no) - 1)), 1
    )
    return remaining_regrinds, life_extension_pct, warranted, scrap_recommended


def recondition_rebate(life_extension_pct, units_returned):
    return int(
        round_half_up(
            D(life_extension_pct) / Decimal(100) * Decimal(units_returned) * REBATE_BASIS_CENTS,
            0,
        )
    )


# ----------------------------------------------------------------- grinding
def grinding_tolerance_class(measured_diameter_dev_um):
    d = abs(D(measured_diameter_dev_um))
    if d <= IT6_MAX_UM:
        return "IT6"
    if d <= IT7_MAX_UM:
        return "IT7"
    if d <= IT8_MAX_UM:
        return "IT8"
    return "OUT_OF_TOLERANCE"
