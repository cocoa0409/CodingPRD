"""The twelve calculation rules (PRD sections 2.5, 2.11, 3.2, 3.6, 3.8, 3.9).

Every arithmetic step runs on decimal.Decimal and every explicit rounding step
uses ROUND_HALF_UP, so a value exactly at the midpoint rounds away from zero.
Floats are never used for money or engineering arithmetic.
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 60

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)


def D(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return None
    return Decimal(str(value))


def rhu(value, places):
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------ constants

MIN_NPSH_MARGIN_M = Decimal("0.60")
MAX_REWORK_CYCLES = 2
WARRANTY_MONTHS = 36
POWER_CONSTANT = Decimal("0.00272407")
MOTOR_SERVICE_FACTOR = Decimal("1.10")
CLEARANCE_BAND_WIDTH = Decimal("0.15")
NPSH_TEST_TOLERANCE_M = Decimal("0.30")
NPSHA_CLAIM_MARGIN_M = Decimal("0.60")
ADMIN_FEE_RATE = Decimal("0.075")

BALANCE_GRADE_G = {
    "G1_0": Decimal("1.0"),
    "G2_5": Decimal("2.5"),
    "G6_3": Decimal("6.3"),
}

GRADE_TOLERANCES = {
    "GRADE_1B": {"head_pct": Decimal("3.0"), "eff_pct": Decimal("3.0"), "min_points": 5},
    "GRADE_2B": {"head_pct": Decimal("5.0"), "eff_pct": Decimal("5.0"), "min_points": 5},
    "GRADE_3B": {"head_pct": Decimal("7.0"), "eff_pct": Decimal("7.0"), "min_points": 3},
}

COVERAGE_TIERS = (
    (12, Decimal("1.00")),
    (24, Decimal("0.60")),
    (36, Decimal("0.30")),
)

HANDLING_TIERS = (
    (Decimal("1000"), Decimal("0.12")),
    (Decimal("5000"), Decimal("0.08")),
    (Decimal("20000"), Decimal("0.05")),
)
HANDLING_TOP_RATE = Decimal("0.03")


# ------------------------------------------------------- 1. impeller trim law


def impeller_trim(model, duty):
    """K, r_exact, trimmed diameter (1 dp), diameter ratio, predicted head (2 dp)."""
    shutoff = D(model["shutoff_head_m"])
    bep_head = D(model["bep_head_m"])
    bep_flow = D(model["bep_flow_m3h"])
    max_d = D(model["max_impeller_diameter_mm"])
    duty_head = D(duty["duty_head_m"])
    duty_flow = D(duty["duty_flow_m3h"])

    k = (shutoff - bep_head) / (bep_flow ** 2)
    r_exact = ((duty_head + k * duty_flow ** 2) / shutoff).sqrt()
    trimmed = rhu(r_exact * max_d, 1)
    ratio = trimmed / max_d
    predicted_head = rhu(ratio ** 2 * shutoff - k * duty_flow ** 2, 2)
    return {
        "k": k,
        "r_exact": r_exact,
        "trimmed_impeller_diameter_mm": trimmed,
        "diameter_ratio": ratio,
        "predicted_head_m": predicted_head,
    }


# --------------------------------------------------- 2. efficiency derating


def viscosity_factor(viscosity_cst):
    v = D(viscosity_cst)
    if v <= 20:
        return Decimal("1.00")
    if v <= 100:
        return Decimal("0.94")
    if v <= 400:
        return Decimal("0.86")
    return Decimal("0.74")


def abrasive_penalty(service_class, solids_pct):
    solids = D(solids_pct)
    if service_class in ("CLEAN", "CORROSIVE"):
        return Decimal("0.0")
    if service_class == "ABRASIVE":
        return Decimal("2.5") + Decimal("0.30") * solids
    if service_class == "CORROSIVE_ABRASIVE":
        return Decimal("3.5") + Decimal("0.30") * solids
    return Decimal("0.0")


def efficiency_and_power(model, duty, config, trim):
    ratio = trim["diameter_ratio"]
    bep_flow = D(model["bep_flow_m3h"])
    duty_flow = D(duty["duty_flow_m3h"])

    trimmed_bep_flow = bep_flow * ratio
    flow_ratio = duty_flow / trimmed_bep_flow

    off_bep = Decimal("40.0") * (ONE - flow_ratio) ** 2
    if off_bep > Decimal("12.0"):
        off_bep = Decimal("12.0")

    trim_penalty = (ONE - ratio) * HUNDRED * Decimal("0.45")
    if trim_penalty < 0:
        trim_penalty = Decimal("0.0")

    v_factor = viscosity_factor(duty["viscosity_cst"])
    abrasive = abrasive_penalty(config["service_class"], duty["solids_pct"])

    raw = (D(model["bep_efficiency_pct"]) - off_bep - trim_penalty - abrasive) * v_factor
    if raw < Decimal("20.0"):
        raw = Decimal("20.0")
    predicted_efficiency = rhu(raw, 2)

    shaft_power = rhu(
        D(duty["specific_gravity"])
        * duty_flow
        * trim["predicted_head_m"]
        * POWER_CONSTANT
        / (predicted_efficiency / HUNDRED),
        2,
    )
    min_motor = rhu(shaft_power * MOTOR_SERVICE_FACTOR, 2)
    return {
        "flow_ratio": flow_ratio,
        "predicted_efficiency_pct": predicted_efficiency,
        "predicted_shaft_power_kw": shaft_power,
        "min_motor_kw": min_motor,
    }


# --------------------------------------------------- 3. NPSH margin chain


def npsh_chain(model, duty, flow_ratio):
    npshr_catalog = rhu(D(model["npshr_at_bep_m"]) * (flow_ratio ** Decimal("1.6")), 2)
    npsha = D(duty["npsha_available_m"])
    provisional = rhu(npsha - npshr_catalog, 2)
    if provisional < Decimal("0.5"):
        factor = Decimal("1.35")
    elif provisional < Decimal("1.5"):
        factor = Decimal("1.25")
    elif provisional < Decimal("3.0"):
        factor = Decimal("1.15")
    else:
        factor = Decimal("1.10")
    npshr_certified = rhu(npshr_catalog * factor, 2)
    margin = rhu(npsha - npshr_certified, 2)
    return {
        "npshr_catalog_m": npshr_catalog,
        "npsh_provisional_margin_m": provisional,
        "npsh_safety_factor_applied": factor,
        "npshr_certified_m": npshr_certified,
        "npsh_margin_m": margin,
    }


# ------------------------------------------- 4. balance / clearance envelope


def allowable_unbalance(model):
    g = BALANCE_GRADE_G[model["balance_grade"]]
    return rhu(g * Decimal(9549) * D(model["rotor_mass_kg"]) / D(model["rated_speed_rpm"]), 2)


def clearance_band(config):
    low = D(config["min_running_clearance_mm"])
    high = rhu(low + CLEARANCE_BAND_WIDTH, 2)
    return low, high


# ------------------------------------------------------- 5. certified curve


def speed_ratio(model, run):
    if run["correction_basis"] == "RATED_SPEED_CORRECTED":
        return D(model["rated_speed_rpm"]) / D(run["test_speed_rpm"])
    return ONE


def reported_points(model, run, points):
    """Reported (speed-corrected) point set, sorted by reported flow then created_at."""
    n = speed_ratio(model, run)
    rows = []
    for point in points:
        row = {
            "point": point,
            "reported_flow_m3h": rhu(D(point["measured_flow_m3h"]) * n, 2),
            "reported_head_m": rhu(D(point["measured_head_m"]) * n ** 2, 2),
            "reported_power_kw": rhu(D(point["measured_power_kw"]) * n ** 3, 2),
        }
        if point.get("measured_npsh3_m") is None:
            row["reported_npsh3_m"] = None
        else:
            row["reported_npsh3_m"] = rhu(D(point["measured_npsh3_m"]) * n ** 2, 2)
        rows.append(row)
    rows.sort(key=lambda r: (r["reported_flow_m3h"], r["point"]["_created_at"], r["point"]["_seq"]))
    return n, rows


def interpolate(rows, target, clamp=False):
    """Linear interpolation on the already-rounded reported values.

    Returns (head, power) as Decimals, or None when the target flow is not
    bracketed and clamping is not permitted.
    """
    if not rows:
        return None
    target = D(target)
    exact = [r for r in rows if r["reported_flow_m3h"] == target]
    if exact:
        return exact[0]["reported_head_m"], exact[0]["reported_power_kw"]
    if target < rows[0]["reported_flow_m3h"] or target > rows[-1]["reported_flow_m3h"]:
        if not clamp:
            return None
        edge = rows[0] if target < rows[0]["reported_flow_m3h"] else rows[-1]
        return edge["reported_head_m"], edge["reported_power_kw"]
    low = None
    high = None
    for row in rows:
        if row["reported_flow_m3h"] < target:
            low = row
        elif high is None:
            high = row
    if low is None or high is None:
        return None
    span = high["reported_flow_m3h"] - low["reported_flow_m3h"]
    if span == 0:
        return low["reported_head_m"], low["reported_power_kw"]
    f = (target - low["reported_flow_m3h"]) / span
    head = low["reported_head_m"] + f * (high["reported_head_m"] - low["reported_head_m"])
    power = low["reported_power_kw"] + f * (high["reported_power_kw"] - low["reported_power_kw"])
    return head, power


# -------------------------------------------- 6. warranty settlement ladder


def coverage_factor(months_since_ship):
    for bound, factor in COVERAGE_TIERS:
        if months_since_ship <= bound:
            return factor
    return None


def settlement(lines, factor):
    subtotal_raw = ZERO
    per_line = []
    for line in lines:
        covered = rhu(D(line["gross_amount"]) * factor, 2)
        per_line.append(covered)
        subtotal_raw += covered
    subtotal = rhu(subtotal_raw, 2)
    admin_fee = rhu(subtotal * ADMIN_FEE_RATE, 2)
    total = rhu(subtotal + admin_fee, 2)
    return per_line, subtotal, admin_fee, total


# ------------------------------------------------- 7. kit allocation charge


def handling_rate(parts_extended):
    for bound, rate in HANDLING_TIERS:
        if parts_extended <= bound:
            return rate
    return HANDLING_TOP_RATE


def allocation_charge(kit, model, requested_qty):
    if kit["preferred_generation"] != model["generation"]:
        penalty = D(kit["substitution_penalty_pct"])
    else:
        penalty = ZERO
    parts_extended = rhu(
        D(requested_qty) * D(kit["unit_price"]) * (ONE + penalty / HUNDRED), 2
    )
    rate = handling_rate(parts_extended)
    handling_fee = rhu(parts_extended * rate, 2)
    total = rhu(parts_extended + handling_fee, 2)
    return {
        "substitution_penalty_applied_pct": penalty,
        "parts_extended": parts_extended,
        "handling_rate": rate,
        "handling_fee": handling_fee,
        "total_charge": total,
    }


# --------------------------------------------------------- 8. whole months


def add_months(start, months):
    year = start.year + (start.month - 1 + months) // 12
    month = (start.month - 1 + months) % 12 + 1
    day = start.day
    while True:
        try:
            return start.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


def whole_months_between(start, end):
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if add_months(start, months) > end:
        months -= 1
    return months
