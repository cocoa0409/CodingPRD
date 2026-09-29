"""The nine calculation rules (PRD 1.3 / 2.7)."""
import re
from datetime import timedelta
from decimal import Decimal

from core import (DB, ceil_int, credentials_of_staff, days_between, find, month_of,
                  newest_credential, now, rhu, today, to_date, where)

REQUIRED_CREDENTIALS = {
    "SITE_MANAGER": ["CPR_AED"],
    "GROUP_EX_INSTRUCTOR": ["GROUP_EX_CERT"],
    "PERSONAL_TRAINER": ["PT_CERT"],
    "WELLNESS_COORDINATOR": ["FIRST_AID"],
}

LIVE_CREDENTIAL_STATUSES = ("VERIFIED", "EXPIRING_SOON")

OPEN_SESSION_STATUSES = ("SCHEDULED", "STAFFED", "STAFFING_AT_RISK")
CANCELLED_SESSION_STATUSES = ("CANCELLED_NO_COVER", "CANCELLED_CLIENT", "CANCELLED_FACILITY")

MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

READINESS_THRESHOLD = 70
COMMITTED_MINUTES_CAP = 6000
PRIVACY_FLOOR = 5


# --------------------------------------------------------------------------
# 1. session_labor_cost
# --------------------------------------------------------------------------
def paid_minutes_for(session, role_on_session):
    minutes = session["scheduled_minutes"]
    if role_on_session == "LEAD":
        minutes = minutes + 15
    return minutes


def assignment_labor_cost(staff, paid_minutes):
    return rhu(Decimal(staff["hourly_cost_cents"]) * Decimal(paid_minutes) / Decimal(60))


def session_labor_cost(session):
    total = 0
    for assignment in where("assignment", session_id=session["id"]):
        if assignment["status"] == "COMPLETED":
            total += assignment["labor_cost_cents"]
    return total


# --------------------------------------------------------------------------
# 2. staff_readiness_index
# --------------------------------------------------------------------------
def credential_score(staff):
    required = staff.get("required_credential_types") or []
    saw_expiring = False
    for credential_type in required:
        newest = newest_credential(staff["id"], credential_type)
        if newest is None:
            return 0
        if newest["status"] not in LIVE_CREDENTIAL_STATUSES:
            return 0
        if newest["status"] == "EXPIRING_SOON":
            saw_expiring = True
    if saw_expiring:
        return 60
    return 100


def drill_score(staff):
    last = to_date(staff.get("last_drill_on"))
    if last is None:
        return 0
    age = days_between(today(), last)
    if age < 0:
        return 100
    if age <= 90:
        return 100
    if age <= 180:
        return 60
    return 0


def coverage_score(staff):
    committed = staff.get("committed_minutes_current_period") or 0
    if committed <= COMMITTED_MINUTES_CAP:
        return 100
    excess = committed - COMMITTED_MINUTES_CAP
    penalty = 5 * ceil_int(Decimal(excess) / Decimal(60))
    return max(0, 100 - penalty)


def readiness_index(staff):
    cred = credential_score(staff)
    if cred == 0:
        # An unverified / expired / rejected required credential collapses the
        # whole index to 0 (PRD 3.2: a fresh hire scores 0; a rejection or an
        # expiry recomputes the holder to 0).
        return 0
    weighted = (Decimal("0.5") * Decimal(cred)
                + Decimal("0.3") * Decimal(drill_score(staff))
                + Decimal("0.2") * Decimal(coverage_score(staff)))
    return rhu(weighted)


def holds_live_credential(staff_id, credential_type):
    for credential in credentials_of_staff(staff_id):
        if credential["credential_type"] == credential_type and \
                credential["status"] in LIVE_CREDENTIAL_STATUSES:
            return True
    return False


# --------------------------------------------------------------------------
# 3. program_attainment (dual variant)
# --------------------------------------------------------------------------
def _counted_records_for_session(session_id):
    return [p for p in where("participation", session_id=session_id) if p["status"] == "COUNTED"]


def attainment_parts(offering):
    counted_done = 0
    forecast_open = 0
    counted_final = 0
    for session in where("session", offering_id=offering["id"]):
        status = session["status"]
        if status in ("IN_PROGRESS", "COMPLETED"):
            counted = len(_counted_records_for_session(session["id"]))
            counted_done += counted
            if status == "COMPLETED":
                counted_final += counted
        elif status in OPEN_SESSION_STATUSES:
            forecast_open += session["forecast_attendance"]
    return counted_done, forecast_open, counted_final


def attainment_pct(numerator, target):
    if not target:
        return 0
    return rhu(Decimal(numerator) * Decimal(100) / Decimal(target))


def compute_attainment(offering):
    counted_done, forecast_open, counted_final = attainment_parts(offering)
    target = offering["participation_target"]
    return {
        "counted_done": counted_done,
        "forecast_open": forecast_open,
        "counted_final": counted_final,
        "provisional_attainment_pct": attainment_pct(counted_done + forecast_open, target),
        "final_attainment_pct": attainment_pct(counted_final, target),
    }


# --------------------------------------------------------------------------
# 4. incentive_points_award
# --------------------------------------------------------------------------
WEEKLY_POINTS_CAP = 60
BASE_POINTS = 10
STREAK_BONUS = 5
STREAK_MIN_DAYS = 3


def incentive_award(member_id):
    instant = now()
    week_start_date = instant.date() - timedelta(days=instant.weekday())
    week_start = instant.replace(year=week_start_date.year, month=week_start_date.month,
                                 day=week_start_date.day, hour=0, minute=0, second=0,
                                 microsecond=0)
    week_points = 0
    prior_days = set()
    day = instant.date()
    window_start = day - timedelta(days=7)
    for record in where("participation", member_id=member_id):
        if record["status"] != "COUNTED":
            continue
        check_in = record["check_in_utc"]
        if check_in >= week_start:
            week_points += record["points_awarded"]
        check_in_date = check_in.astimezone(instant.tzinfo).date()
        if window_start <= check_in_date and check_in_date != day:
            prior_days.add(check_in_date)
    distinct_prior_days = len(prior_days)
    streak = distinct_prior_days >= STREAK_MIN_DAYS
    candidate = BASE_POINTS + (STREAK_BONUS if streak else 0)
    headroom = max(0, WEEKLY_POINTS_CAP - week_points)
    awarded = min(candidate, headroom)
    return {
        "points_awarded": awarded,
        "points_capped": candidate > headroom,
        "streak_bonus_applied": streak,
    }


# --------------------------------------------------------------------------
# 5. aed_readiness_status
# --------------------------------------------------------------------------
AED_INSPECTION_MAX_AGE_DAYS = 30
AED_CONSUMABLE_WARN_DAYS = 30


def aed_readiness_status(asset):
    if asset["asset_type"] != "AED":
        return "NOT_APPLICABLE"
    day = today()
    pad = to_date(asset.get("pad_expiry_on"))
    battery = to_date(asset.get("battery_expiry_on"))
    inspection = to_date(asset.get("last_inspection_on"))
    if asset["status"] != "IN_SERVICE":
        return "NOT_READY"
    if pad is None or battery is None:
        return "NOT_READY"
    if pad <= day or battery <= day:
        return "NOT_READY"
    if inspection is None or days_between(day, inspection) > AED_INSPECTION_MAX_AGE_DAYS:
        return "NOT_READY"
    soonest = pad if pad <= battery else battery
    if days_between(soonest, day) <= AED_CONSUMABLE_WARN_DAYS:
        return "PADS_EXPIRING"
    return "READY"


def contract_has_ready_aed(contract_id):
    for asset in where("asset", contract_id=contract_id):
        if asset["asset_type"] == "AED" and asset["readiness_status"] == "READY":
            return True
    return False


# --------------------------------------------------------------------------
# 6. equipment_downtime_credit
# --------------------------------------------------------------------------
DOWNTIME_GRACE_DAYS = 3
DOWNTIME_RATE_AED = 1200
DOWNTIME_RATE_OTHER = 250


def downtime_credit_cents(contract_id):
    total = 0
    for asset in where("asset", contract_id=contract_id):
        days = asset.get("out_of_service_days_current_period") or 0
        chargeable = max(0, days - DOWNTIME_GRACE_DAYS)
        rate = DOWNTIME_RATE_AED if asset["asset_type"] == "AED" else DOWNTIME_RATE_OTHER
        total += chargeable * rate
    return total


# --------------------------------------------------------------------------
# 7. coverage_shortfall_penalty
# --------------------------------------------------------------------------
PENALTY_FREE_SESSIONS = 1
PENALTY_RATE = Decimal("0.015")
PENALTY_CAP_RATE = Decimal("0.05")


def coverage_penalty_cents(contract):
    if contract["fee_structure"] != "MANAGEMENT_FEE":
        return 0
    fee = contract.get("management_fee_cents") or 0
    chargeable = max(0, (contract.get("uncovered_session_count") or 0) - PENALTY_FREE_SESSIONS)
    per_session = rhu(Decimal(fee) * PENALTY_RATE)
    cap = rhu(Decimal(fee) * PENALTY_CAP_RATE)
    return min(chargeable * per_session, cap)


# --------------------------------------------------------------------------
# 8. monthly_invoice_amounts (dual variant)
# --------------------------------------------------------------------------
def _period_labor_and_direct(contract_id, period_month):
    labor = 0
    direct = 0
    for session in sessions_of_contract_cached(contract_id):
        if session["status"] != "COMPLETED":
            continue
        if month_of(session.get("completed_at")) != period_month:
            continue
        direct += session.get("direct_supply_cost_cents") or 0
        for assignment in where("assignment", session_id=session["id"]):
            if assignment["status"] == "COMPLETED":
                labor += assignment.get("labor_cost_cents") or 0
    return labor, direct


def sessions_of_contract_cached(contract_id):
    out = []
    for offering in where("offering", contract_id=contract_id):
        out.extend(where("session", offering_id=offering["id"]))
    return out


def markup_rate_for(base):
    if base <= 15000:
        return Decimal("0.12")
    if base <= 30000:
        return Decimal("0.09")
    return Decimal("0.07")


def volume_credit_rate_for(gross):
    if gross >= 70000:
        return Decimal("0.03")
    if gross >= 35000:
        return Decimal("0.015")
    return Decimal("0")


def compute_invoice_amounts(contract, period_month, fee_structure_snapshot):
    labor, direct = _period_labor_and_direct(contract["id"], period_month)
    downtime = downtime_credit_cents(contract["id"])
    result = {
        "labor_subtotal_cents": labor,
        "program_direct_cost_cents": direct,
        "admin_markup_cents": 0,
        "volume_credit_cents": 0,
        "downtime_credit_cents": downtime,
        "coverage_penalty_cents": 0,
        "gross_amount_cents": 0,
        "net_amount_cents": 0,
        "nte_capped": False,
    }
    if fee_structure_snapshot == "MANAGEMENT_FEE":
        penalty = coverage_penalty_cents(contract)
        gross = contract.get("management_fee_cents") or 0
        result["coverage_penalty_cents"] = penalty
        result["gross_amount_cents"] = gross
        result["net_amount_cents"] = gross - penalty - downtime
        return result
    base = labor + direct
    markup = rhu(Decimal(base) * markup_rate_for(base))
    gross = base + markup
    credit = rhu(Decimal(gross) * volume_credit_rate_for(gross))
    net = gross - credit - downtime
    remaining = max(0, (contract.get("not_to_exceed_cents") or 0)
                    - (contract.get("ytd_billed_cents") or 0))
    if net > remaining:
        net = remaining
        result["nte_capped"] = True
    result["admin_markup_cents"] = markup
    result["volume_credit_cents"] = credit
    result["gross_amount_cents"] = gross
    result["net_amount_cents"] = net
    return result


# --------------------------------------------------------------------------
# 9. contract_utilization_rollup
# --------------------------------------------------------------------------
MEMBER_CLASSES = ("EMPLOYEE", "DEPENDENT", "RETIREE")


def utilization_rollup(contract, period_month):
    members = {m["id"]: m for m in where("member", contract_id=contract["id"])}
    per_class_participants = {}
    per_class_checkins = {}
    for member_class in MEMBER_CLASSES:
        per_class_participants[member_class] = set()
        per_class_checkins[member_class] = 0
    participants = set()
    for record in DB.all("participation"):
        if record["status"] != "COUNTED":
            continue
        if month_of(record["check_in_utc"]) != period_month:
            continue
        member = members.get(record["member_id"])
        if member is None:
            continue
        participants.add(member["id"])
        member_class = member["member_class"]
        if member_class in per_class_participants:
            per_class_participants[member_class].add(member["id"])
            per_class_checkins[member_class] += 1
    eligible = contract.get("eligible_member_count") or 0
    distinct = len(participants)
    if eligible == 0:
        rate = 0
    else:
        rate = rhu(Decimal(distinct) * Decimal(100) / Decimal(eligible))
    target = contract.get("participation_target_pct") or 0
    breakdown = []
    suppressed_count = 0
    for member_class in MEMBER_CLASSES:
        count = len(per_class_participants[member_class])
        suppressed = count < PRIVACY_FLOOR
        if suppressed:
            suppressed_count += 1
        breakdown.append({
            "member_class": member_class,
            "suppressed": suppressed,
            "participant_count": None if suppressed else count,
            "check_in_count": None if suppressed else per_class_checkins[member_class],
        })
    return {
        "period_month": period_month,
        "eligible_member_count": eligible,
        "distinct_participants": distinct,
        "participation_rate_pct": rate,
        "participation_target_pct": target,
        "target_variance_pct": rate - target,
        "class_breakdown": breakdown,
        "suppressed_cohort_count": suppressed_count,
    }
