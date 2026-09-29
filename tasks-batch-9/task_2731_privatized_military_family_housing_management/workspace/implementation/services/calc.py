"""All 18 calculations from PRD section 2.7 / 3.x.

Every money figure is an integer number of cents; every rounding step is
half-up, performed with decimal.Decimal (never float, never round()).
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import days_in_month, parse_date

# --------------------------------------------------------------- rounding core

ONE = Decimal(1)
CENT = Decimal("0.01")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value):
    """Round half up to a whole integer."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round half up to two decimal places, returned as a Decimal."""
    return dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def num(value):
    """Render a Decimal as a JSON-friendly number."""
    return float(value)


# ------------------------------------------------------------- rank derivation

def rank_category(pay_grade):
    band = pay_grade[0]
    number = int(pay_grade[1:])
    if band == "E":
        return "JUNIOR_ENLISTED" if number <= 6 else "SENIOR_ENLISTED"
    if band == "W":
        return "WARRANT_OFFICER"
    return "JUNIOR_OFFICER" if number <= 3 else "SENIOR_OFFICER"


# ------------------------------------------------------------------------- ages

def age_years(dob, reference):
    years = reference.year - dob.year
    if (reference.month, reference.day) < (dob.month, dob.day):
        years -= 1
    return years


# --------------------------------------------------- effective control date (1)

def effective_control_date(pcs_orders_date, deployed):
    d = pcs_orders_date
    if deployed:
        d = d - timedelta(days=30)
    return d


# ------------------------------------------------------ bedroom eligibility (2)

def bedroom_eligibility(dependents, control_date):
    """Base one bedroom for the sponsor (and spouse), then children and others."""
    children = [d for d in dependents
                if d["relationship"] == "CHILD" and d.get("is_full_time_custody")]
    others = [d for d in dependents
              if d["relationship"] == "OTHER_AUTHORIZED" and d.get("is_full_time_custody")]

    private = 0
    shared_by_gender = {"MALE": 0, "FEMALE": 0}
    for child in children:
        age = age_years(parse_date(child["date_of_birth"]), control_date)
        if age >= 10:
            private += 1
        else:
            gender = child.get("gender")
            if gender in shared_by_gender:
                shared_by_gender[gender] += 1
            else:
                shared_by_gender[gender] = 1

    shared_rooms = 0
    for gender in ("MALE", "FEMALE"):
        count = shared_by_gender.get(gender, 0)
        if count:
            shared_rooms += -(-count // 2)
    for gender, count in shared_by_gender.items():
        if gender in ("MALE", "FEMALE"):
            continue
        if count:
            shared_rooms += -(-count // 2)

    raw = 1 + shared_rooms + private + len(others)
    if raw < 1:
        raw = 1
    if raw > 5:
        raw = 5
    return raw


def full_time_dependent_count(dependents):
    return len([d for d in dependents if d.get("is_full_time_custody")])


# ----------------------------------------------------------- gross rent (3, 4)

UNIT_TYPE_ADJUSTMENT = {
    "SFH": Decimal("0.00"),
    "DUPLEX": Decimal("-0.02"),
    "TOWNHOME": Decimal("-0.03"),
    "APARTMENT": Decimal("-0.05"),
}
HISTORIC_UPLIFT = Decimal("0.015")


def gross_rent(monthly_rate_cents, unit_type, historic_flag):
    monthly = dec(monthly_rate_cents)
    adjusted = rhu(monthly * (ONE + UNIT_TYPE_ADJUSTMENT[unit_type]))
    if historic_flag:
        adjusted += rhu(monthly * HISTORIC_UPLIFT)
    return min(adjusted, int(monthly_rate_cents))


def daily_rent(net_rent_cents):
    return rhu(dec(net_rent_cents) * Decimal(12) / Decimal(365))


# ------------------------------------------------------- work order priority (6)

BASE_TIER = {
    "NO_HEAT": 3, "NO_WATER": 3, "GAS_LEAK": 3, "SEWAGE_BACKUP": 3,
    "ELECTRICAL": 2, "PLUMBING_LEAK": 2, "HVAC": 2,
    "MOLD_SUSPECTED": 2, "LEAD_SUSPECTED": 2,
    "APPLIANCE": 1, "COSMETIC": 1, "GROUNDS": 1,
}
TIER_TO_CLASS = {3: "EMERGENCY", 2: "URGENT", 1: "ROUTINE"}


def priority_class(category, habitability_impact, vulnerable_child):
    tier = BASE_TIER[category]
    if habitability_impact:
        tier = max(tier, 2)
    if category in ("MOLD_SUSPECTED", "LEAD_SUSPECTED"):
        tier = max(tier, 2)
    if habitability_impact and vulnerable_child:
        tier = 3
    return TIER_TO_CLASS[tier]


# ------------------------------------------------------------- SLA clocks (7)

SLA_HOURS = {
    "EMERGENCY": (4, 24),
    "URGENT": (24, 72),
    "ROUTINE": (120, 720),
}
HABITABILITY_CAP_HOURS = 72


def sla_due(priority, reported_at, habitability_impact):
    response_hours, completion_hours = SLA_HOURS[priority]
    reported_at = reported_at.replace(microsecond=0)
    response_due = reported_at + timedelta(hours=response_hours)
    completion_due = reported_at + timedelta(hours=completion_hours)
    if habitability_impact:
        capped = reported_at + timedelta(hours=HABITABILITY_CAP_HOURS)
        if capped < completion_due:
            completion_due = capped
    return response_due, completion_due


# ------------------------------------------------------- escalation ladder (8)

ESCALATION_HOURS = {
    "EMERGENCY": {1: 0, 2: 24},
    "URGENT": {1: 24, 2: 96},
    "ROUTINE": {1: 240, 2: 480},
}


def escalation_due(priority, target_level, completion_due_at, now):
    required_seconds = ESCALATION_HOURS[priority][target_level] * 3600
    overdue_seconds = (now - completion_due_at).total_seconds()
    return overdue_seconds >= required_seconds


# ------------------------------------------------------- hazard severity (9, 10)

def hazard_severity(hazard_type, affected_area_sqft, lead_level_ppm):
    if hazard_type == "MOLD":
        value = dec(affected_area_sqft if affected_area_sqft is not None else 0)
        if value <= Decimal(10):
            return "SEVERITY_1"
        if value <= Decimal(30):
            return "SEVERITY_2"
        return "SEVERITY_3"
    value = dec(lead_level_ppm if lead_level_ppm is not None else 0)
    if hazard_type == "LEAD_PAINT":
        if value < Decimal(5000):
            return "SEVERITY_1"
        if value < Decimal(10000):
            return "SEVERITY_2"
        return "SEVERITY_3"
    # LEAD_WATER
    if value < Decimal(10):
        return "SEVERITY_1"
    if value < Decimal(15):
        return "SEVERITY_2"
    return "SEVERITY_3"


def displacement_required(severity, child_under_six_present):
    if severity == "SEVERITY_3":
        return True
    return severity == "SEVERITY_2" and bool(child_under_six_present)


# ------------------------------------------------------- rent abatement (11)

def abatement_days(assessment_date):
    last_day = days_in_month(assessment_date.year, assessment_date.month)
    end = date(assessment_date.year, assessment_date.month, last_day)
    return (end - assessment_date).days + 1


def abatement_amount(daily_rent_cents, days):
    return -(int(daily_rent_cents) * int(days))


# ------------------------------------------------------ lodging figures (12)

ROOM_RATE_CAP_CENTS = 25000
MEAL_ALLOWANCE_CENTS = 6900


def lodging_figures(nightly_rate_cents, occupants_count, start, actual_end, daily_rent_cents):
    nights = (actual_end - start).days
    if nights < 0:
        nights = 0
    per_night = min(int(nightly_rate_cents), ROOM_RATE_CAP_CENTS) \
        + MEAL_ALLOWANCE_CENTS * int(occupants_count)
    authorized = per_night * nights
    rent_abatement = int(daily_rent_cents) * nights
    return nights, per_night, authorized, rent_abatement


# --------------------------------------------------- termination settlement (13)

TIER_THRESHOLD_CENTS = 100000
LOW_TIER_RATE = Decimal("0.05")
HIGH_TIER_RATE = Decimal("0.08")
ZERO_RATE = Decimal("0.00")
NO_FEE_REASONS = ("PCS", "DEPLOYMENT", "SEPARATION", "LANDLORD")


def prorated_days(termination_effective_date):
    period_start = date(termination_effective_date.year, termination_effective_date.month, 1)
    return (termination_effective_date - period_start).days + 1


def settlement(daily_rent_cents, termination_effective_date, awarded_credit_cents,
               termination_reason):
    days = prorated_days(termination_effective_date)
    prorated_rent = int(daily_rent_cents) * days
    fee_base = prorated_rent - int(awarded_credit_cents)
    if fee_base < 0:
        fee_base = 0
    tier_rate = LOW_TIER_RATE if fee_base < TIER_THRESHOLD_CENTS else HIGH_TIER_RATE
    reason_rate = ZERO_RATE if termination_reason in NO_FEE_REASONS else tier_rate
    fee = rhu(dec(fee_base) * reason_rate)
    return {
        "prorated_days": days,
        "prorated_rent_cents": prorated_rent,
        "fee_base_cents": fee_base,
        "early_termination_fee_cents": fee,
        "settlement_total_cents": fee_base + fee,
    }


# ---------------------------------------------------- occupancy rate (14, 15)

def occupancy_rate(basis, units, leases_by_unit, first_day, last_day):
    unit_count = len(units)
    if unit_count == 0:
        return rhu2(Decimal(0))
    if basis == "MONTH_END_SNAPSHOT":
        numerator = len([u for u in units if u["status"] == "OCCUPIED"])
        denominator = unit_count
    else:
        numerator = 0
        for unit in units:
            covered = set()
            for lease in leases_by_unit.get(unit["id"], []):
                if lease["occupancy_status"] not in ("OCCUPIED", "NOTICE_GIVEN"):
                    continue
                start = parse_date(lease["start_date"])
                end = last_day
                if lease.get("termination_effective_date"):
                    ted = parse_date(lease["termination_effective_date"])
                    if ted < end:
                        end = ted
                if start < first_day:
                    start = first_day
                cursor = start
                while cursor <= end:
                    covered.add(cursor)
                    cursor = cursor + timedelta(days=1)
            numerator += len(covered)
        denominator = unit_count * ((last_day - first_day).days + 1)
    if denominator == 0:
        return rhu2(Decimal(0))
    return rhu2(Decimal(100) * dec(numerator) / dec(denominator))


# ------------------------------------------------- performance incentive (16)

OCCUPANCY_BANDS = (
    (Decimal(96), Decimal("1.25")),
    (Decimal(92), Decimal("1.00")),
    (Decimal(85), Decimal("0.50")),
)
PENALTY_PER_ESCALATION = Decimal("0.05")
PENALTY_CAP = Decimal("0.50")
CONTRIBUTION_RATE = Decimal("0.10")


def occupancy_multiplier(occupancy_rate_pct):
    value = dec(occupancy_rate_pct)
    for threshold, multiplier in OCCUPANCY_BANDS:
        if value >= threshold:
            return multiplier
    return Decimal("0.00")


def habitability_penalty(escalated_count):
    penalty = PENALTY_PER_ESCALATION * Decimal(int(escalated_count))
    return penalty if penalty < PENALTY_CAP else PENALTY_CAP


def incentive_fee(net_collected_cents, incentive_base_pct, occupancy_rate_pct,
                  escalated_count):
    base_fee = rhu(dec(net_collected_cents) * dec(incentive_base_pct))
    multiplier = occupancy_multiplier(occupancy_rate_pct)
    penalty = habitability_penalty(escalated_count)
    fee = rhu(dec(base_fee) * multiplier * (ONE - penalty))
    return base_fee, multiplier, penalty, fee


def contribution_from(amount_cents):
    return rhu(dec(amount_cents) * CONTRIBUTION_RATE)
