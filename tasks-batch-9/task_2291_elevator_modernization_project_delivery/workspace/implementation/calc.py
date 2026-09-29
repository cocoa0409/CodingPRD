"""Calculation rules: scoring, pricing, posture, interval geometry, credits."""

import calendar
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, fmt_dt, ordered

ZERO = Decimal(0)

# --- condition scoring -----------------------------------------------------
POINTS = {"EXCELLENT": 100, "GOOD": 80, "FAIR": 55, "POOR": 25, "FAILED": 0}
CONDITION_GRADES = ["EXCELLENT", "GOOD", "FAIR", "POOR", "FAILED", "NOT_OBSERVED"]
W_CONTROLLER = Decimal("0.45")
W_MACHINE = Decimal("0.30")
W_DOOR = Decimal("0.25")
COMPONENTS = [
    ("controller_condition", W_CONTROLLER),
    ("machine_condition", W_MACHINE),
    ("door_equipment_condition", W_DOOR),
]

SCOPE_TIERS = ["CONTROLLER_ONLY", "CONTROLLER_DOOR", "CONTROLLER_MACHINE", "FULL_REPLACEMENT"]
TIER_RANK = {"CONTROLLER_ONLY": 1, "CONTROLLER_DOOR": 2, "CONTROLLER_MACHINE": 3, "FULL_REPLACEMENT": 4}
TIER_MULTIPLIER = {
    "CONTROLLER_ONLY": Decimal("1.00"),
    "CONTROLLER_DOOR": Decimal("1.15"),
    "CONTROLLER_MACHINE": Decimal("1.30"),
    "FULL_REPLACEMENT": Decimal("1.45"),
}

SCORE_BASES = ["OBSERVED_ONLY", "IMPUTED_FAILED"]
CREDIT_BASES = ["THIRTY_360", "ACTUAL_CALENDAR"]


def rhu(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    return int(rhu(value, 0))


def dec2(value):
    return rhu(value, 2)


def as_number(value):
    """Render a Decimal for the JSON payload."""
    if value is None:
        return None
    return float(value)


def score_survey(survey, basis):
    """Returns (score Decimal 2dp, observed_weight_total Decimal)."""
    if basis == "OBSERVED_ONLY":
        numerator = ZERO
        denominator = ZERO
        for field, weight in COMPONENTS:
            grade = survey[field]
            if grade == "NOT_OBSERVED":
                continue
            numerator += Decimal(POINTS[grade]) * weight
            denominator += weight
        if denominator == 0:
            return Decimal("0.00"), Decimal("0.00")
        return dec2(numerator / denominator), denominator
    numerator = ZERO
    for field, weight in COMPONENTS:
        grade = survey[field]
        points = Decimal(POINTS.get(grade, 0)) if grade != "NOT_OBSERVED" else ZERO
        numerator += points * weight
    return dec2(numerator), Decimal("1.00")


def tier_for_score(score):
    if score >= Decimal("80.00"):
        return "CONTROLLER_ONLY"
    if score >= Decimal("60.00"):
        return "CONTROLLER_DOOR"
    if score >= Decimal("35.00"):
        return "CONTROLLER_MACHINE"
    return "FULL_REPLACEMENT"


# --- relationship walkers --------------------------------------------------

def car_of_option(option):
    return db.cars.get(option["car_id"])


def project_of(car):
    return db.projects.get(car["project_id"]) if car else None


def jurisdiction_of_project(project):
    return db.jurisdictions.get(project["jurisdiction_id"]) if project else None


def triggers_of_option(option_id):
    return ordered([t for t in db.code_triggers.values() if t["scope_option_id"] == option_id])


def orders_of_option(option_id):
    return ordered([o for o in db.procurement_orders.values() if o["scope_option_id"] == option_id])


def options_of_car(car_id):
    return ordered([o for o in db.scope_options.values() if o["car_id"] == car_id])


def surveys_of_car(car_id):
    return ordered([s for s in db.surveys.values() if s["car_id"] == car_id])


def windows_of_car(car_id):
    return ordered([w for w in db.outage_windows.values() if w["car_id"] == car_id])


def cars_of_group(group_id):
    return ordered([c for c in db.cars.values() if c["group_id"] == group_id])


def groups_of_project(project_id):
    return ordered([grp for grp in db.groups.values() if grp["project_id"] == project_id])


def cars_of_project(project_id):
    return ordered([c for c in db.cars.values() if c["project_id"] == project_id])


def latest_countersigned_survey(car_id):
    rows = [s for s in surveys_of_car(car_id) if s["status"] == "COUNTERSIGNED"]
    return rows[-1] if rows else None


def live_option_of_car(car_id):
    for option in options_of_car(car_id):
        if option["status"] in ("DRAFT", "SUBMITTED", "APPROVED"):
            return option
    return None


def approved_option_of_car(car_id):
    for option in options_of_car(car_id):
        if option["status"] == "APPROVED":
            return option
    return None


# --- conserved counters ----------------------------------------------------

def group_car_count(group):
    return len(cars_of_group(group["id"]))


def group_cars_in_service(group):
    return len([c for c in cars_of_group(group["id"]) if c["work_status"] != "OUTAGE_ACTIVE"])


def project_car_count(project):
    return len(cars_of_project(project["id"]))


def project_approved_scope_value(project):
    total = 0
    for option in db.scope_options.values():
        if option["status"] != "APPROVED":
            continue
        car = db.cars.get(option["car_id"])
        if car is not None and car["project_id"] == project["id"]:
            total += option["total_price_cents"]
    return total


def project_of_reservation_id(reservation):
    order = db.procurement_orders.get(reservation["procurement_order_id"])
    if order is None:
        return None
    option = db.scope_options.get(order["scope_option_id"])
    if option is None:
        return None
    car = db.cars.get(option["car_id"])
    if car is None:
        return None
    return db.projects.get(car["project_id"])


def held_reservations_of_project(project_id):
    rows = []
    for reservation in ordered(list(db.staging_reservations.values())):
        if reservation["status"] != "HELD":
            continue
        owner = project_of_reservation_id(reservation)
        if owner is not None and owner["id"] == project_id:
            rows.append(reservation)
    return rows


def project_staging_committed(project):
    return sum(r["sqft"] for r in held_reservations_of_project(project["id"]))


def project_active_outage_count(project):
    count = 0
    for window in db.outage_windows.values():
        if window["status"] != "ACTIVE":
            continue
        car = db.cars.get(window["car_id"])
        if car is not None and car["project_id"] == project["id"]:
            count += 1
    return count


def groups_below_floor(project):
    return len(
        [
            grp
            for grp in groups_of_project(project["id"])
            if group_cars_in_service(grp) < grp["min_cars_in_service"]
        ]
    )


STAGING_PRESSURE_PCT = 85


def downtime_posture(project):
    if groups_below_floor(project) > 0:
        return "FROZEN"
    if project_active_outage_count(project) >= project["max_concurrent_outages"]:
        return "RESTRICTED"
    if project_staging_committed(project) * 100 > project["staging_area_sqft"] * STAGING_PRESSURE_PCT:
        return "RESTRICTED"
    return "OPEN"


# --- scope option pricing --------------------------------------------------

def code_upgrade_cents(option):
    car = car_of_option(option)
    project = project_of(car)
    jurisdiction = jurisdiction_of_project(project)
    surcharge = jurisdiction["permit_surcharge_pct"] if jurisdiction else ZERO
    total = 0
    for trigger in triggers_of_option(option["id"]):
        if trigger["status"] not in ("PRICED", "SATISFIED"):
            continue
        cost = Decimal(trigger["cost_cents"] or 0)
        total += rhu_cents(cost * (Decimal(1) + surcharge))
    return total


ESCALATION_PCT_TIER_1 = Decimal("0.0000")
ESCALATION_PCT_TIER_2 = Decimal("0.0300")
ESCALATION_PCT_TIER_3 = Decimal("0.0650")
ESCALATION_PCT_TIER_4 = Decimal("0.1100")

VOLUME_BREAK_1 = 15000000
VOLUME_BREAK_2 = 30000000
VOLUME_BREAK_3 = 60000000
VOLUME_DISCOUNT_PCT_1 = Decimal("0.0000")
VOLUME_DISCOUNT_PCT_2 = Decimal("0.0200")
VOLUME_DISCOUNT_PCT_3 = Decimal("0.0450")
VOLUME_DISCOUNT_PCT_4 = Decimal("0.0700")


def escalation_pct_for(days):
    if days <= 60:
        return ESCALATION_PCT_TIER_1
    if days <= 120:
        return ESCALATION_PCT_TIER_2
    if days <= 180:
        return ESCALATION_PCT_TIER_3
    return ESCALATION_PCT_TIER_4


def volume_discount_pct_for(subtotal):
    if subtotal < VOLUME_BREAK_1:
        return VOLUME_DISCOUNT_PCT_1
    if subtotal < VOLUME_BREAK_2:
        return VOLUME_DISCOUNT_PCT_2
    if subtotal < VOLUME_BREAK_3:
        return VOLUME_DISCOUNT_PCT_3
    return VOLUME_DISCOUNT_PCT_4


def max_lead_time_days(option):
    leads = [o["lead_time_days"] for o in orders_of_option(option["id"]) if o["status"] != "CANCELLED"]
    return max(leads) if leads else 0


def recompute_pricing(option, force=False):
    """Run the pinned pricing chain.  Frozen once the option leaves DRAFT/SUBMITTED."""
    if not force and option["status"] not in ("DRAFT", "SUBMITTED"):
        return
    option["code_upgrade_cents"] = code_upgrade_cents(option)
    pre_escalation = option["base_price_cents"] + option["code_upgrade_cents"]
    lead = max_lead_time_days(option)
    option["max_lead_time_days"] = lead
    escalation_pct = escalation_pct_for(lead)
    option["escalation_pct"] = escalation_pct
    option["escalation_fee_cents"] = rhu_cents(Decimal(pre_escalation) * escalation_pct)
    subtotal = pre_escalation + option["escalation_fee_cents"]
    discount_pct = volume_discount_pct_for(subtotal)
    option["volume_discount_pct"] = discount_pct
    option["volume_discount_cents"] = rhu_cents(Decimal(subtotal) * discount_pct)
    option["total_price_cents"] = subtotal - option["volume_discount_cents"]


# --- interval geometry -----------------------------------------------------

def staging_peak_sqft(project_id, new_start, new_end, exclude_ids=()):
    """Additive, pointwise peak of HELD footage over the half-open new hold."""
    candidates = [
        r
        for r in held_reservations_of_project(project_id)
        if r["id"] not in exclude_ids
        and r["_hold_start"] < new_end
        and new_start < r["_hold_end"]
    ]
    if not candidates:
        return 0
    boundaries = set([new_start])
    for reservation in candidates:
        if new_start <= reservation["_hold_start"] < new_end:
            boundaries.add(reservation["_hold_start"])
    peak = 0
    for instant in boundaries:
        concurrent = sum(
            r["sqft"] for r in candidates if r["_hold_start"] <= instant < r["_hold_end"]
        )
        if concurrent > peak:
            peak = concurrent
    return peak


def outage_buffer_conflict(project, group_id, new_start, new_end, exclude_window_id=None):
    """Pairwise, buffer-inflated conflict over the group's PLANNED/ACTIVE windows."""
    buffer_delta = timedelta(hours=project["outage_buffer_hours"])
    for window in ordered(list(db.outage_windows.values())):
        if window["status"] not in ("PLANNED", "ACTIVE"):
            continue
        if exclude_window_id is not None and window["id"] == exclude_window_id:
            continue
        car = db.cars.get(window["car_id"])
        if car is None or car["group_id"] != group_id:
            continue
        if new_start < window["_end_at"] + buffer_delta and window["_start_at"] < new_end + buffer_delta:
            return True
    return False


# --- warranty credit / maintenance pricing --------------------------------

def group_factor_for(car_count):
    if car_count <= 1:
        return Decimal("1.00")
    if car_count <= 3:
        return Decimal("0.93")
    return Decimal("0.88")


def per_car_monthly_cents(contract, car):
    option = approved_option_of_car(car["id"])
    tier = option["tier"] if option else None
    multiplier = TIER_MULTIPLIER.get(tier, Decimal("1.00"))
    group = db.groups.get(car["group_id"])
    car_count = group_car_count(group) if group else 0
    factor = group_factor_for(car_count)
    return rhu_cents(Decimal(contract["monthly_base_cents"]) * multiplier * factor)


def thirty_360_days(anchor, end):
    d1 = min(anchor.day, 30)
    d2 = min(end.day, 30)
    return 360 * (end.year - anchor.year) + 30 * (end.month - anchor.month) + (d2 - d1)


def actual_calendar_days(anchor, end):
    return (end.date() - anchor.date()).days


def credit_for(transition, contract, basis):
    """Returns (day_count, per_car_monthly_cents, credit_cents)."""
    car = db.cars.get(transition["car_id"])
    if contract is None or car is None:
        return 0, 0, 0
    rate = per_car_monthly_cents(contract, car)
    anchor = contract["_coverage_start"]
    end = transition["_warranty_end"]
    if basis == "THIRTY_360":
        days = thirty_360_days(anchor, end)
        divisor = Decimal(30)
    else:
        days = actual_calendar_days(anchor, end)
        divisor = Decimal(365)
    if end <= anchor:
        return days, rate, 0
    if basis == "THIRTY_360":
        credit = rhu_cents(Decimal(rate) * Decimal(days) / divisor)
    else:
        credit = rhu_cents(Decimal(rate) * Decimal(days) * Decimal(12) / divisor)
    return days, rate, credit


def add_months(instant, months):
    """Advance an instant by whole calendar months, clamping to month end."""
    month_index = instant.month - 1 + months
    year = instant.year + month_index // 12
    month = month_index % 12 + 1
    day = min(instant.day, calendar.monthrange(year, month)[1])
    return instant.replace(year=year, month=month, day=day)


def add_days(instant, days):
    return instant + timedelta(days=days)


def whole_days_between(start, end):
    """Elapsed whole days, discarding any remainder short of 86,400 seconds."""
    seconds = (end - start).total_seconds()
    return int(seconds // 86400)


def hours_between(start, end):
    """Hours from start to end, carried to two decimal places."""
    seconds = Decimal(str((end - start).total_seconds()))
    return dec2(seconds / Decimal(3600))


def fmt(instant):
    return fmt_dt(instant)
