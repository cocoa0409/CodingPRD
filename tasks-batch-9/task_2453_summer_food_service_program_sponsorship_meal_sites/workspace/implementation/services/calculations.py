"""Program constants and every derived calculation (PRD sec 3.2 - sec 3.9).

All monetary arithmetic is integer cents; the only fractional quantities are the
per-meal reimbursement rates, which are carried as Decimal and rounded half-up
to whole cents at the pinned granularity of (line item, meal type).
"""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

import db

# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
SPONSOR_TYPES = ("SCHOOL_FOOD_AUTHORITY", "GOVERNMENT", "NONPROFIT", "CAMP_OPERATOR")
EXPERIENCE_STATUSES = ("NEW", "EXPERIENCED")
DATA_SOURCES = ("SCHOOL_DATA", "CENSUS_ACS")
SITE_TYPES = ("OPEN", "RESTRICTED_OPEN", "CLOSED_ENROLLED", "CAMP", "MIGRANT")
PRODUCTION_MODES = ("SELF_PREP", "VENDED")
MEAL_TYPES = ("BREAKFAST", "AM_SNACK", "LUNCH", "PM_SNACK", "SUPPER")
TEMPERATURE_CLASSES = ("COLD", "HOT")
VISIT_TYPES = ("FIRST_WEEK", "FULL_REVIEW", "FOLLOW_UP")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
SEVERITY_ORDER = {"MINOR": 1, "MAJOR": 2, "CRITICAL": 3}
FORECAST_METHODS = ("PEAK_PROJECTION", "DECAY_WEIGHTED")
PROGRAM_MONTHS = (6, 7, 8)

# --------------------------------------------------------------------------
# Constants (SCAFFOLD calculations, PRD sec 3.4 - sec 3.9)
# --------------------------------------------------------------------------
AREA_ELIGIBILITY_THRESHOLD_PCT = Decimal("50.00")
CENSUS_ACS_THRESHOLD_PCT = Decimal("55.00")

RATE_CENTS = {
    "RURAL_OR_SELF_PREP": {
        "BREAKFAST": Decimal("268.75"),
        "AM_SNACK": Decimal("126.25"),
        "LUNCH": Decimal("470.50"),
        "PM_SNACK": Decimal("126.25"),
        "SUPPER": Decimal("470.50"),
    },
    "OTHER": {
        "BREAKFAST": Decimal("263.25"),
        "AM_SNACK": Decimal("123.00"),
        "LUNCH": Decimal("462.75"),
        "PM_SNACK": Decimal("123.00"),
        "SUPPER": Decimal("462.75"),
    },
}

ADMIN_CAP_PCT = Decimal("0.20")
ADMIN_RATIO_LIMIT = Decimal("0.2000")
ADVANCE_CAP_PCT = Decimal("0.25")
SECOND_MEAL_ALLOWANCE_PCT = Decimal("0.02")

COLD_MAX_F = Decimal("41.0")
HOT_MIN_F = Decimal("135.0")
MAX_HOLDING_MINUTES = 240

FIRST_WEEK_VISIT_DAYS = 4
FULL_REVIEW_DAYS = 28
MAX_VISITS_PER_MONITOR_DAY = 3
MEAL_SERVICE_GAP_MINUTES = 60

COMPLIANCE_FLAG_THRESHOLD = 2
ESCALATION_REJECTION_THRESHOLD = 2
RESPONSE_DAYS_BY_SEVERITY = {"CRITICAL": 5, "MAJOR": 15, "MINOR": 30}

FORECAST_WINDOW_DAYS = 5
OUTREACH_UPLIFT_FACTOR = Decimal("1.10")
DECAY_FACTOR = Decimal("0.6")
WASTE_TOLERANCE_PCT = Decimal("0.10")


# --------------------------------------------------------------------------
# Small numeric helpers
# --------------------------------------------------------------------------
def half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_int(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_CEILING))


def decimal_out(value):
    """JSON representation of a Decimal quantity."""
    if value is None:
        return None
    if value == value.to_integral_value():
        return float(value)
    return float(value)


# --------------------------------------------------------------------------
# Budget ratio and advance cap
# --------------------------------------------------------------------------
def admin_cost_ratio(operating_cents, admin_cents):
    """admin / (operating + admin), four decimal places, round half-up."""
    total = Decimal(operating_cents) + Decimal(admin_cents)
    if total == 0:
        return Decimal("0.0000")
    ratio = Decimal(admin_cents) / total
    return ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def advance_cap_cents(approved_operating_cents, approved_admin_cents):
    """floor(0.25 * (approved operating + approved admin))."""
    total = Decimal((approved_operating_cents or 0) + (approved_admin_cents or 0))
    return floor_int(total * ADVANCE_CAP_PCT)


# --------------------------------------------------------------------------
# Point-of-service meal classification (PRD sec 3.6)
# --------------------------------------------------------------------------
def day_entries(day):
    return [
        entry
        for entry in db.store.count_entries.values()
        if entry["meal_service_day_id"] == day["id"]
    ]


def classify_day(day, site, entries=None):
    """Classify a day's count entries.

    Returns a dict with the day-level counters plus ``per_type`` mapping each
    meal type to (reimbursable_first, reimbursable_second).
    """
    if entries is None:
        entries = day_entries(day)

    declared = [service["meal_type"] for service in day.get("meal_services") or []]
    extras = sorted(
        {entry["meal_type"] for entry in entries if entry["meal_type"] not in declared}
    )
    order = declared + extras

    production = day.get("production_counts") or {}
    counted_first = 0
    counted_second = 0
    counted_adult = 0
    per_type = {}

    for meal_type in order:
        net_first = 0
        net_second = 0
        net_adult = 0
        for entry in entries:
            if entry["meal_type"] != meal_type:
                continue
            sign = -1 if entry["entry_kind"] == "REVERSAL" else 1
            net_first += sign * entry["first_meals"]
            net_second += sign * entry["second_meals"]
            net_adult += sign * entry["adult_meals"]

        counted_first += net_first
        counted_second += net_second
        counted_adult += net_adult

        # Step 1 — attendance cap.
        reimb_first = min(net_first, site["approved_max_attendance"])
        if reimb_first < 0:
            reimb_first = 0
        # Step 2 — second meals only at camps, allowance floored.
        if site["site_type"] == "CAMP":
            allowance = floor_int(SECOND_MEAL_ALLOWANCE_PCT * Decimal(reimb_first))
            reimb_second = min(net_second, allowance)
            if reimb_second < 0:
                reimb_second = 0
        else:
            reimb_second = 0
        # Step 3 — production waterfall, self-prep days only.
        if day.get("production_mode") == "SELF_PREP":
            available = production.get(meal_type, 0) or 0
            if reimb_first > available:
                reimb_first = available
            remaining = available - reimb_first
            if remaining < 0:
                remaining = 0
            if reimb_second > remaining:
                reimb_second = remaining
        # Step 4 — adult meals are never reimbursable.
        per_type[meal_type] = (reimb_first, reimb_second)

    reimbursable = sum(first + second for first, second in per_type.values())
    counted_total = counted_first + counted_second + counted_adult
    production_total = sum(production.values()) if production else 0
    discarded = day.get("discarded_meals") or 0
    leftover = production_total - counted_total - discarded
    if leftover < 0:
        leftover = 0

    return {
        "counted_first_meals": counted_first,
        "counted_second_meals": counted_second,
        "counted_adult_meals": counted_adult,
        "reimbursable_meals": reimbursable,
        "non_reimbursable_meals": counted_total - reimbursable,
        "leftover_meals": leftover,
        "production_total": production_total,
        "per_type": per_type,
    }


def write_day_totals(day, site, entries=None):
    """Recompute and store the day's derived counters.  Returns the result."""
    result = classify_day(day, site, entries)
    db.apply_changes(
        day,
        {
            "counted_first_meals": result["counted_first_meals"],
            "counted_second_meals": result["counted_second_meals"],
            "counted_adult_meals": result["counted_adult_meals"],
            "reimbursable_meals": result["reimbursable_meals"],
            "non_reimbursable_meals": result["non_reimbursable_meals"],
            "leftover_meals": result["leftover_meals"],
        },
    )
    return result


def unserved_production(day, result=None):
    """Production not yet served, floored at 0 (food-safety discard basis)."""
    if result is None:
        site = db.store.sites.get(day["site_id"])
        result = classify_day(day, site)
    unserved = (
        result["production_total"]
        - result["counted_first_meals"]
        - result["counted_second_meals"]
        - result["counted_adult_meals"]
    )
    return unserved if unserved > 0 else 0


# --------------------------------------------------------------------------
# Holding-log breach evaluation (PRD sec 3.6)
# --------------------------------------------------------------------------
def holding_minutes(food_received_at, measured_at):
    delta = measured_at - food_received_at
    return int(delta.total_seconds() // 60) if delta.total_seconds() >= 0 else -int(
        (-delta.total_seconds()) // 60
    )


def evaluate_breach(site, temperature_class, temperature_f, minutes_held):
    """Returns (breach_flag, breach_reason) in the fixed precedence order."""
    if not site.get("is_open_air"):
        return (False, None)
    if temperature_class == "COLD" and temperature_f > COLD_MAX_F:
        return (True, "TEMP_OUT_OF_BAND")
    if temperature_class == "HOT" and temperature_f < HOT_MIN_F:
        return (True, "TEMP_OUT_OF_BAND")
    if minutes_held > MAX_HOLDING_MINUTES:
        return (True, "HOLDING_TIME_EXCEEDED")
    return (False, None)


# --------------------------------------------------------------------------
# Monitoring deadlines (PRD sec 3.7)
# --------------------------------------------------------------------------
def visit_due_date(visit, site):
    first_operating = db.parse_date(site.get("first_operating_date"))
    if first_operating is None:
        return None
    if visit["visit_type"] == "FIRST_WEEK":
        return db.date_iso(first_operating + db.timedelta(days=FIRST_WEEK_VISIT_DAYS))
    if visit["visit_type"] == "FULL_REVIEW":
        return db.date_iso(first_operating + db.timedelta(days=FULL_REVIEW_DAYS))
    return visit["scheduled_date"]


def visit_is_late(visit):
    due_date = db.parse_date(visit.get("due_date"))
    if due_date is None:
        return False
    status = visit["status"]
    if status in ("CONDUCTED", "REPORT_FILED", "CLOSED"):
        conducted = db.parse_datetime(visit.get("conducted_at"))
        if conducted is None:
            return False
        return conducted.date() > due_date
    if status == "SCHEDULED":
        return db.clock.today() > due_date
    return False


def action_due_date(severity):
    days = RESPONSE_DAYS_BY_SEVERITY[severity]
    return db.date_iso(db.clock.today() + db.timedelta(days=days))


def next_severity(severity):
    if severity == "MINOR":
        return "MAJOR"
    return "CRITICAL"


# --------------------------------------------------------------------------
# Claim money (PRD sec 3.8)
# --------------------------------------------------------------------------
def rate_class_for_site(site):
    if site.get("is_rural") or site.get("production_mode") == "SELF_PREP":
        return "RURAL_OR_SELF_PREP"
    return "OTHER"


def line_meals_rate_value(line):
    """Sum of per-(line, meal type) values, each rounded half-up first."""
    rates = RATE_CENTS[line["rate_class"]]
    first_map = line.get("claimed_first_meals_by_type") or {}
    second_map = line.get("claimed_second_meals_by_type") or {}
    disallowed = line.get("disallowed_counts_by_type") or {}
    total = 0
    for meal_type in sorted(first_map.keys()):
        net = (
            (first_map.get(meal_type) or 0)
            + (second_map.get(meal_type) or 0)
            - (disallowed.get(meal_type) or 0)
        )
        rate = rates.get(meal_type)
        if rate is None:
            continue
        total += half_up(Decimal(net) * rate)
    return total


def claim_meals_rate_value(claim):
    total = 0
    for line in claim_lines(claim):
        total += line["meals_rate_value_cents"] or 0
    return total


def claim_lines(claim):
    return db.ordered(
        [
            line
            for line in db.store.line_items.values()
            if line["meal_claim_id"] == claim["id"]
        ]
    )


def preliminary_reimbursement(claim):
    """meals value + claimed admin cost, no disallowances and no caps."""
    return (claim.get("meals_rate_value_cents") or 0) + (
        claim.get("claimed_admin_cost_cents") or 0
    )


def final_reimbursement_breakdown(claim):
    """The five pinned steps of the final variant."""
    meals_value = claim.get("meals_rate_value_cents") or 0
    claimed_operating = claim.get("claimed_operating_cost_cents") or 0
    claimed_admin = claim.get("claimed_admin_cost_cents") or 0
    operating_reimbursement = min(meals_value, claimed_operating)
    admin_cap = floor_int(Decimal(operating_reimbursement) * ADMIN_CAP_PCT)
    admin_reimbursement = min(claimed_admin, admin_cap)
    return {
        "meals_rate_value_cents": meals_value,
        "operating_reimbursement_cents": operating_reimbursement,
        "admin_cap_cents": admin_cap,
        "admin_reimbursement_cents": admin_reimbursement,
        "gross_cents": operating_reimbursement + admin_reimbursement,
    }


# --------------------------------------------------------------------------
# Attendance forecast (PRD sec 3.9)
# --------------------------------------------------------------------------
def forecast_window(site, service_date):
    days = [
        day
        for day in db.store.days.values()
        if day["site_id"] == site["id"]
        and day["status"] == "FINALIZED"
        and db.parse_date(day["service_date"]) < service_date
    ]
    days.sort(key=lambda day: (day["service_date"], day["_seq"]), reverse=True)
    return days[:FORECAST_WINDOW_DAYS]


def attendance_forecast(site, service_date, method):
    window = forecast_window(site, service_date)
    if not window:
        return None
    attendance = [day.get("counted_first_meals") or 0 for day in window]
    ceiling = site["approved_max_attendance"]

    if method == "PEAK_PROJECTION":
        forecast = ceil_int(Decimal(max(attendance)) * OUTREACH_UPLIFT_FACTOR)
    else:
        weight = Decimal("1")
        weighted_sum = Decimal("0")
        weight_sum = Decimal("0")
        for value in attendance:
            weighted_sum += weight * Decimal(value)
            weight_sum += weight
            weight = weight * DECAY_FACTOR
        forecast = half_up(weighted_sum / weight_sum)
    if forecast > ceiling:
        forecast = ceiling

    most_recent = window[0]
    production = most_recent.get("production_counts") or {}
    most_recent_production = sum(production.values()) if production else 0
    tolerance = floor_int(Decimal(forecast) * WASTE_TOLERANCE_PCT)
    waste_risk = most_recent_production > forecast + tolerance

    return {
        "site_id": site["id"],
        "service_date": db.date_iso(service_date),
        "method": method,
        "forecast_meals": forecast,
        "prior_days_used": len(window),
        "most_recent_production_meals": most_recent_production,
        "waste_risk_flag": waste_risk,
    }
