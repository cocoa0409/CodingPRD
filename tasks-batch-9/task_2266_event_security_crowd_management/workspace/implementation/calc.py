"""Every derived figure in the system (PRD 2.9, 3.1-3.9).

All arithmetic runs in Decimal. Money is whole cents held as int; ratios are
quantized Decimals rendered as JSON numbers.
"""

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, getcontext

getcontext().prec = 50

ZERO = Decimal(0)
ONE = Decimal(1)


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places):
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def cents(value):
    """Round a Decimal amount to a whole cent, half-up."""
    return int(D(value).quantize(ONE, rounding=ROUND_HALF_UP))


def ceil_int(value):
    return int(D(value).quantize(ONE, rounding=ROUND_CEILING))


def floor_int(value):
    return int(D(value).quantize(ONE, rounding=ROUND_FLOOR))


def num(value):
    """Render a quantized Decimal for JSON output."""
    if value is None:
        return None
    return float(value)


# --------------------------------------------------------------------------
# 3.1 zone occupancy ceiling
# --------------------------------------------------------------------------

AREA_ALLOWANCE_SQM = D("0.65")
PERSONS_PER_EXIT_UNIT = 100


def zone_max_safe_occupancy(posted_capacity, floor_area_sqm, exit_units):
    area_ceiling = floor_int(D(floor_area_sqm) / AREA_ALLOWANCE_SQM)
    egress_ceiling = int(exit_units) * PERSONS_PER_EXIT_UNIT
    return min(int(posted_capacity), area_ceiling, egress_ceiling)


# --------------------------------------------------------------------------
# 3.2 composite threat score and risk tier
# --------------------------------------------------------------------------

THREAT_POINTS = {"LOW": 0, "GUARDED": 8, "ELEVATED": 18, "HIGH": 30, "SEVERE": 44}
PROTEST_POINTS = {"NONE": 0, "POSSIBLE": 6, "LIKELY": 15}
PROFILE_POINTS = {"SEATED": 0, "FAMILY": 2, "GENERAL_ADMISSION": 10, "MOSH_PIT": 20}
LAYOUT_POINTS_PER_LEVEL = 3
ALCOHOL_POINTS = 7
VIP_POINTS = 5
DENSITY_POINTS_AT_FULL_HOUSE = 30
DENSITY_PRESSURE_CAP = D(25)
CROWD_FACTOR_CAP = D("1.35")
CROWD_FACTOR_PER_UNIT = D("0.04")
SCORE_CAP = D(100)


def composite_threat_score(
    basis_attendance,
    gross_capacity,
    threat_level_input,
    protest_likelihood,
    crowd_profile,
    layout_complexity_score,
    alcohol_served,
    vip_present,
    history_incident_rate,
):
    load_ratio = D(basis_attendance) / D(gross_capacity)
    density_pressure = round_half_up(load_ratio * D(DENSITY_POINTS_AT_FULL_HOUSE), 2)
    if density_pressure > DENSITY_PRESSURE_CAP:
        density_pressure = DENSITY_PRESSURE_CAP
    base_points = (
        D(THREAT_POINTS[threat_level_input])
        + D(PROTEST_POINTS[protest_likelihood])
        + D(PROFILE_POINTS[crowd_profile])
        + D(LAYOUT_POINTS_PER_LEVEL) * D(layout_complexity_score)
        + (D(ALCOHOL_POINTS) if alcohol_served else ZERO)
        + (D(VIP_POINTS) if vip_present else ZERO)
        + density_pressure
    )
    crowd_factor = ONE + CROWD_FACTOR_PER_UNIT * D(history_incident_rate)
    if crowd_factor > CROWD_FACTOR_CAP:
        crowd_factor = CROWD_FACTOR_CAP
    score = round_half_up(base_points * crowd_factor, 2)
    if score > SCORE_CAP:
        score = SCORE_CAP
    return score


def risk_tier(score):
    score = D(score)
    if score >= D(70):
        return "T4"
    if score >= D(50):
        return "T3"
    if score >= D(30):
        return "T2"
    return "T1"


# --------------------------------------------------------------------------
# 3.3 staffing requirement matrix
# --------------------------------------------------------------------------

TIER_GUARD_RATIO = {"T1": D("1.5"), "T2": D("2.5"), "T3": D("4.0"), "T4": D("6.0")}
SHARE_PERIMETER = D("0.30")
SHARE_INGRESS = D("0.25")
SHARE_FLOOR = D("0.35")
SHARE_EXIT = D("0.10")
GUARDS_PER_DOOR = 1
SPAN_OF_CONTROL = 10
SUPERVISOR_SPAN = 5
SURGE_SHARE = D("0.55")
BAG_SHARE = D("0.60")
CLEARANCE_WINDOW_MIN = 65
BAG_LANE_PPH = 180
NOBAG_LANE_PPH = 420
MIN_CALL_HOURS = 4
FLOOR_RATE_CENTS_PER_HOUR = 1800


def required_staff_matrix(basis_attendance, tier, door_count):
    raw = D(basis_attendance) / D(1000) * TIER_GUARD_RATIO[tier]
    perimeter = ceil_int(raw * SHARE_PERIMETER)
    ingress = ceil_int(raw * SHARE_INGRESS)
    floor_guards = ceil_int(raw * SHARE_FLOOR)
    exit_guards = max(ceil_int(raw * SHARE_EXIT), int(door_count) * GUARDS_PER_DOOR)
    line = perimeter + ingress + floor_guards + exit_guards
    return {
        "required_perimeter_guards": perimeter,
        "required_ingress_guards": ingress,
        "required_floor_guards": floor_guards,
        "required_exit_guards": exit_guards,
        "required_line_guards": line,
    }


def supervisor_span(required_line_guards):
    first_line = ceil_int(D(required_line_guards) / D(SPAN_OF_CONTROL))
    second_line = ceil_int(D(first_line) / D(SUPERVISOR_SPAN)) if first_line > SUPERVISOR_SPAN else 0
    supervisors = first_line + second_line
    return {
        "required_supervisors": supervisors,
        "required_total_staff": int(required_line_guards) + supervisors,
    }


def required_screening_lanes(basis_attendance):
    surge = ceil_int(D(basis_attendance) * SURGE_SHARE)
    bag = ceil_int(D(surge) * BAG_SHARE)
    nobag = surge - bag
    bag_capacity = D(BAG_LANE_PPH) * D(CLEARANCE_WINDOW_MIN) / D(60)
    nobag_capacity = D(NOBAG_LANE_PPH) * D(CLEARANCE_WINDOW_MIN) / D(60)
    return ceil_int(D(bag) / bag_capacity) + ceil_int(D(nobag) / nobag_capacity)


def minimum_staffing_cost_floor_cents(required_total_staff):
    return int(required_total_staff) * MIN_CALL_HOURS * FLOOR_RATE_CENTS_PER_HOUR


# --------------------------------------------------------------------------
# 3.6 assignment cost
# --------------------------------------------------------------------------

OVERTIME_THRESHOLD_HOURS = D(8)
OVERTIME_MULTIPLIER = D("1.5")
NIGHT_DIFFERENTIAL_CENTS_PER_HOUR = D(150)
SUBCONTRACT_ADMIN_FEE_CENTS = 1200
NIGHT_START_HOUR = 22
NIGHT_END_HOUR = 6


def hours_between(start_dt, end_dt):
    seconds = D((end_dt - start_dt).total_seconds())
    return round_half_up(seconds / D(3600), 2)


def night_differential_applies(window_start_dt):
    hour = window_start_dt.hour
    return hour >= NIGHT_START_HOUR or hour < NIGHT_END_HOUR


def cost_for_hours(hours, base_hourly_rate_cents, night_applies, employment_type, markup_pct):
    """The pinned three-level cost computation of PRD 3.6."""
    hours = D(hours)
    straight = hours if hours < OVERTIME_THRESHOLD_HOURS else OVERTIME_THRESHOLD_HOURS
    overtime = hours - OVERTIME_THRESHOLD_HOURS
    if overtime < ZERO:
        overtime = ZERO
    rate = D(base_hourly_rate_cents)
    base_pay = cents(rate * straight) + cents(rate * OVERTIME_MULTIPLIER * overtime)
    night_pay = cents(NIGHT_DIFFERENTIAL_CENTS_PER_HOUR * hours) if night_applies else 0
    subtotal = base_pay + night_pay
    if employment_type == "SUBCONTRACTED":
        marked = cents(D(subtotal) * (ONE + D(markup_pct if markup_pct is not None else 0)))
        line_cost = marked + SUBCONTRACT_ADMIN_FEE_CENTS
        pay_basis = "SUBCONTRACT"
    else:
        line_cost = subtotal
        pay_basis = "EMPLOYEE_OT" if overtime > ZERO else "EMPLOYEE_STRAIGHT"
    return line_cost, pay_basis, overtime


# --------------------------------------------------------------------------
# 3.8 crowd density
# --------------------------------------------------------------------------

DENSITY_THRESHOLDS = (
    (D("4.000"), "CRITICAL"),
    (D("3.200"), "RED"),
    (D("2.000"), "AMBER"),
)
DENSITY_RANK = {"GREEN": 0, "AMBER": 1, "RED": 2, "CRITICAL": 3}


def classify_density(value):
    value = D(value)
    for threshold, level in DENSITY_THRESHOLDS:
        if value >= threshold:
            return level
    return "GREEN"


# --------------------------------------------------------------------------
# 3.7 lane throughput
# --------------------------------------------------------------------------

SECONDARY_SCREEN_SHARE = D("0.04")
SECONDARY_SCREEN_COST = D("2.5")
LANE_DRAG_FACTOR = ONE - SECONDARY_SCREEN_SHARE * SECONDARY_SCREEN_COST


def lane_throughput(nominal_throughput_pph, assigned_operator_count, operator_capacity, status):
    if status != "OPEN":
        return 0
    staffing_factor = D(assigned_operator_count) / D(operator_capacity)
    if staffing_factor > ONE:
        staffing_factor = ONE
    return floor_int(D(nominal_throughput_pph) * staffing_factor * LANE_DRAG_FACTOR)


# --------------------------------------------------------------------------
# 3.8 incident response SLA
# --------------------------------------------------------------------------

SLA_BUDGET_MINUTES = {"MINOR": D(15), "MODERATE": D(10), "SEVERE": D(5), "CRITICAL": D(3)}
SEVERITY_RANK = {"MINOR": 0, "MODERATE": 1, "SEVERE": 2, "CRITICAL": 3}


def incident_response_metrics(reported_dt, triaged_dt, severity_at_report):
    seconds = D((triaged_dt - reported_dt).total_seconds())
    response_minutes = round_half_up(seconds / D(60), 2)
    breached = response_minutes > SLA_BUDGET_MINUTES[severity_at_report]
    return response_minutes, breached


def minutes_between(start_dt, end_dt):
    seconds = D((end_dt - start_dt).total_seconds())
    return seconds / D(60)
