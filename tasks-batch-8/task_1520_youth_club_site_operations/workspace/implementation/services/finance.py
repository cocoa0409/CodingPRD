"""Fiscal calculations (PRD §2.6, §3.2, §3.3, §3.9): eligibility tiers, weekly
fee accrual with scholarship disbursement, fund accounting, meal-claim totals,
and funder-report metrics. All money is integer cents; Decimal with
ROUND_HALF_UP is used for every rounding."""

from decimal import Decimal, ROUND_HALF_UP

import db
from services import core
from services.core import MEAL_TYPES, TIERS, day_end, day_start, _parse_date, _parse_dt

# Eligibility thresholds (scaffold §1.3 constants)
FREE_BASE_CENTS = 1500000
FREE_STEP_CENTS = 500000
REDUCED_BASE_CENTS = 2000000
REDUCED_STEP_CENTS = 650000

TIER_MULTIPLIER = {"FREE": Decimal("0"), "REDUCED": Decimal("0.5"), "PAID": Decimal("1")}
SUMMER_MULTIPLIER = Decimal("1.10")


def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rate4(numerator, denominator):
    """4 decimal places, round half up; 0 when denominator == 0."""
    if denominator == 0:
        return 0
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


def determine_eligibility_tier(household_size, household_income_cents):
    free_limit = FREE_BASE_CENTS + (household_size - 1) * FREE_STEP_CENTS
    reduced_limit = REDUCED_BASE_CENTS + (household_size - 1) * REDUCED_STEP_CENTS
    if household_income_cents <= free_limit:
        return "FREE"
    if household_income_cents <= reduced_limit:
        return "REDUCED"
    return "PAID"


def gross_weekly_fee(site, tier):
    return round_half_up_cents(Decimal(site["base_weekly_fee_cents"]) * TIER_MULTIPLIER[tier])


def fund_available(fund):
    return fund["budget_cents"] - fund["reserved_cents"] - fund["disbursed_cents"]


def recompute_fund_available(fund):
    fund["available_cents"] = fund_available(fund)


def weekly_accrual(site, day):
    """PRD §3.9: run when ISO weekday(day.date) == site.fee_accrual_weekday.
    Processes members ACTIVE/SUSPENDED with approved_at <= day end-of-day,
    ordered by approved_at ASC then created_at ASC. Per member, at most one
    ACTIVE award participates (earliest created_at wins when several)."""
    if _parse_date(day["date"]).isoweekday() != site["fee_accrual_weekday"]:
        return
    day["weekly_fees_accrued"] = True
    end_of_day = day_end(_parse_date(day["date"]))
    members = [
        m for m in db.find("members", site_id=site["id"])
        if m["status"] in ("ACTIVE", "SUSPENDED")
        and m.get("approved_at") is not None
        and _parse_dt(m["approved_at"]) <= end_of_day
    ]
    members.sort(key=lambda m: (m["approved_at"], m["created_at"]))
    funds_touched = set()
    for member in members:
        awards = [a for a in db.find("awards", member_id=member["id"]) if a["status"] == "ACTIVE"]
        awards.sort(key=lambda a: a["created_at"])
        award = awards[0] if awards else None
        gross = member["weekly_fee_cents"] or 0
        disbursement = 0
        if award is not None:
            discount_amount = round_half_up_cents(Decimal(gross) * Decimal(str(award["discount_pct"])))
            disbursement = min(award["weekly_cap_cents"], award["remaining_cap_cents"], discount_amount)
            if disbursement > 0:
                award["disbursed_cents"] += disbursement
                award["remaining_cap_cents"] -= disbursement
                fund = db.get("funds", award["fund_id"])
                fund["reserved_cents"] -= disbursement
                fund["disbursed_cents"] += disbursement
                recompute_fund_available(fund)
                funds_touched.add(fund["id"])
                if award["remaining_cap_cents"] == 0:
                    award["status"] = "EXHAUSTED"
                db.touch(award)
            elif award["remaining_cap_cents"] == 0:
                award["status"] = "EXHAUSTED"
                db.touch(award)
        member["fee_balance_cents"] += gross - disbursement
        db.touch(member)
    for fund_id in funds_touched:
        db.touch(db.get("funds", fund_id))


def seasonal_multiplier(date_str):
    month = int(date_str[5:7])
    return SUMMER_MULTIPLIER if month in (6, 7, 8) else Decimal("1")


def pin_rate_snapshot(site, claim_month):
    """rate_snapshot = site meal_rates_cents + per-day seasonal multiplier pinned
    at claim creation."""
    rates = site["meal_rates_cents"]
    days = _month_days(site["id"], claim_month, statuses=("OPEN", "CLOSED", "RECONCILED"))
    multipliers = {d["date"]: str(seasonal_multiplier(d["date"])) for d in days}
    return {"rates": rates, "multiplier": multipliers}


def _month_days(site_id, month, statuses):
    out = []
    for d in db.find("club_days", site_id=site_id):
        if d["date"][:7] == month and d["status"] in statuses:
            out.append(d)
    out.sort(key=lambda d: d["date"])
    return out


def compute_claim_total(snapshot, site_id, claim_month, statuses):
    """Per (day, meal_type, tier) line: round_half_up(n * rate * multiplier),
    then integer sum of the rounded lines."""
    total = 0
    for day in _month_days(site_id, claim_month, statuses):
        pinned = snapshot["multiplier"].get(day["date"])
        # The seasonal multiplier is a pure function of the date, so a day that
        # did not exist when the snapshot was pinned resolves identically.
        mult = Decimal(pinned) if pinned is not None else seasonal_multiplier(day["date"])
        for meal_type in MEAL_TYPES:
            counts = day["meal_counts"].get(meal_type, {})
            rates = snapshot["rates"].get(meal_type, {})
            for tier in TIERS:
                n = counts.get(tier, 0)
                rate = rates.get(tier, 0)
                line = (Decimal(n) * Decimal(rate) * mult).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                total += int(line)
    return total


def compute_report_metrics(site, report_month, funder_type):
    """PRD §3.9 funder-report computation, over CLOSED+RECONCILED days."""
    included = _month_days(site["id"], report_month, statuses=("CLOSED", "RECONCILED"))
    operating_days = len(included)
    day_ids = {d["id"] for d in included}
    member_days_attended = sum(
        1 for rec in db.all_records("attendance") if rec["club_day_id"] in day_ids
    )
    member_days_enrolled = 0
    site_members = db.find("members", site_id=site["id"])
    for d in included:
        ddate = _parse_date(d["date"])
        end = day_end(ddate)
        start = day_start(ddate)
        for m in site_members:
            approved = m.get("approved_at")
            if approved is None or _parse_dt(approved) > end:
                continue
            withdrawn = m.get("withdrawn_at")
            if withdrawn is not None and not (_parse_dt(withdrawn) > start):
                continue
            member_days_enrolled += 1
    average_daily_attendance = rate4(member_days_attended, operating_days)
    enrollment_basis = rate4(member_days_attended, member_days_enrolled)
    capacity_basis = rate4(member_days_attended, site["youth_capacity"] * operating_days)
    headline = enrollment_basis if funder_type == "UNITED_WAY" else capacity_basis
    meals_served_total = 0
    for d in included:
        for meal_type in MEAL_TYPES:
            for tier in TIERS:
                meals_served_total += d["meal_counts"].get(meal_type, {}).get(tier, 0)
    site_member_ids = {m["id"] for m in site_members}
    incidents_total = sum(
        1 for inc in db.all_records("incidents")
        if inc["member_id"] in site_member_ids and inc["incident_date"][:7] == report_month
    )
    return {
        "operating_days": operating_days,
        "member_days_attended": member_days_attended,
        "member_days_enrolled": member_days_enrolled,
        "average_daily_attendance": average_daily_attendance,
        "attendance_rate_enrollment_basis": enrollment_basis,
        "attendance_rate_capacity_basis": capacity_basis,
        "headline_attendance_rate": headline,
        "meals_served_total": meals_served_total,
        "incidents_total": incidents_total,
    }
