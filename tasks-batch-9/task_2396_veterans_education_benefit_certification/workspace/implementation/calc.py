"""CALC-1 .. CALC-7 (scaffold §1.3 / PRD §3.6-§3.8).

Every monetary quantity is an integer count of cents; every rounding step is
round-half-up and happens exactly where the specification pins it.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from common import by_created, clock_day, day_of, days_between
from db import db

# --- constants pinned by the scaffold --------------------------------------
MHA_MIN_ROP_PCT = 50
ONLINE_MHA_MONTHLY_CENTS = 99650
FULL_MONTH_BILLABLE_DAYS = 30
ANNUAL_CAP_CENTS = 2790000
REPORTING_DEADLINE_DAYS = 30
DEBT_NOTIFICATION_DAYS = 30
COE_PROTECTION_DAYS = 90

LIVE_OVERLAP_STATUSES = ("SUBMITTED", "CERTIFIED", "AMENDMENT_PENDING")
CAP_CHARGING_STATUSES = ("CERTIFIED", "AMENDMENT_PENDING", "TERMINATED")


def D(value):
    return Decimal(str(value))


def rhu(value):
    """Round half up (away from zero) to a whole unit."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# =============================================================================
# CALC-1 — rate of pursuit, training time, modality, monthly housing rate
# =============================================================================
def calc1(credit_hours_total, credit_hours_online, start_day, end_day, program, student):
    certified_days = days_between(start_day, end_day) + 1

    rop = rhu(D(credit_hours_total) * 100 / D(program["full_time_credit_hours"]))
    tier = min(100, rhu(D(rop) / 10) * 10)

    if rop >= 100:
        training_time = "FULL_TIME"
    elif rop >= 75:
        training_time = "THREE_QUARTER"
    elif rop >= 50:
        training_time = "HALF_TIME"
    elif rop >= 25:
        training_time = "QUARTER_TIME"
    else:
        training_time = "LESS_THAN_QUARTER"

    if D(credit_hours_online) == D(credit_hours_total):
        modality = "ONLINE_ONLY"
    elif D(credit_hours_online) == 0:
        modality = "RESIDENTIAL"
    else:
        modality = "MIXED"

    # NOTE the strict > : a rate of pursuit of exactly 50 earns NO housing.
    mha_eligible = student["chapter"] == "CH33" and rop > MHA_MIN_ROP_PCT

    if not mha_eligible:
        housing_base = 0
    elif modality == "ONLINE_ONLY":
        housing_base = ONLINE_MHA_MONTHLY_CENTS
    else:
        housing_base = program["campus_bah_monthly_cents"]

    # single rounding AFTER both percentage multiplications (pinned order)
    mha_monthly_rate_cents = rhu(
        D(housing_base) * D(student["benefit_level_pct"]) * D(tier) / 10000
    )

    return {
        "certified_days": certified_days,
        "rate_of_pursuit_pct": rop,
        "rop_tier_pct": tier,
        "training_time": training_time,
        "modality": modality,
        "mha_eligible": mha_eligible,
        "mha_monthly_rate_cents": mha_monthly_rate_cents,
    }


# =============================================================================
# CALC-2 — term housing total: segment, round per segment, then sum
# =============================================================================
def _month_last_day(day):
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


def _next_month_first(day):
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


def _segments(start_day, end_day, effective_day=None):
    cuts = {start_day}
    cursor = _next_month_first(start_day)
    while cursor <= end_day:
        cuts.add(cursor)
        cursor = _next_month_first(cursor)
    if effective_day is not None and start_day < effective_day <= end_day:
        cuts.add(effective_day)
    starts = sorted(cuts)
    out = []
    for index, seg_start in enumerate(starts):
        if index + 1 < len(starts):
            seg_end = starts[index + 1] - timedelta(days=1)
        else:
            seg_end = end_day
        out.append((seg_start, seg_end))
    return out


def _billable_days(seg_start, seg_end):
    if seg_start.day == 1 and seg_end == _month_last_day(seg_start):
        return FULL_MONTH_BILLABLE_DAYS
    return days_between(seg_start, seg_end) + 1


def calc2_as_certified(start_day, end_day, mha_eligible, monthly_rate_cents):
    if not mha_eligible:
        return 0
    if end_day < start_day:
        return 0
    total = 0
    for seg_start, seg_end in _segments(start_day, end_day):
        billable = _billable_days(seg_start, seg_end)
        total += rhu(D(monthly_rate_cents) * billable / FULL_MONTH_BILLABLE_DAYS)
    return total


def calc2_as_reconciled(start_day, end_day, effective_day, pre_rate_cents, post_rate_cents):
    if end_day < start_day:
        return 0
    total = 0
    for seg_start, seg_end in _segments(start_day, end_day, effective_day):
        billable = _billable_days(seg_start, seg_end)
        rate = pre_rate_cents if seg_end < effective_day else post_rate_cents
        total += rhu(D(rate) * billable / FULL_MONTH_BILLABLE_DAYS)
    return total


# =============================================================================
# CALC-3 — covered tuition, annual cap ledger, Yellow Ribbon gap
# =============================================================================
def net_covered_from_report(gross_tuition_cents, mandatory_fees_cents, tuition_specific_aid_cents):
    """S1. non_tuition_aid_cents is deliberately EXCLUDED."""
    return max(0, gross_tuition_cents + mandatory_fees_cents - tuition_specific_aid_cents)


def calc3_steps_2_to_7(certification, student, net_covered_cents):
    prior = 0
    peers = [
        c for c in db.certifications.values()
        if c["student_id"] == certification["student_id"]
        and c["id"] != certification["id"]
        and c["status"] in CAP_CHARGING_STATUSES
    ]
    term = db.terms.get(certification["term_id"])
    academic_year = term["academic_year"] if term else None
    for peer in by_created(peers):
        peer_term = db.terms.get(peer["term_id"])
        if peer_term is not None and peer_term["academic_year"] == academic_year:
            prior += peer["cap_charged_cents"]

    ay_cap_remaining_before = max(0, ANNUAL_CAP_CENTS - prior)
    capped_base = min(net_covered_cents, ay_cap_remaining_before)
    va_tuition = rhu(D(capped_base) * D(student["benefit_level_pct"]) / 100)
    cap_charged = va_tuition
    yr_gap = net_covered_cents - va_tuition
    return {
        "net_covered_cents": net_covered_cents,
        "ay_cap_remaining_before_cents": ay_cap_remaining_before,
        "va_tuition_cents": va_tuition,
        "cap_charged_cents": cap_charged,
        "yr_gap_cents": yr_gap,
    }


def calc3_step8(certification, agreement):
    """S8 — the Yellow Ribbon school-share / VA-match / out-of-pocket split."""
    yr_gap = certification["yr_gap_cents"]

    spent = 0
    siblings = []
    for award in db.awards.values():
        if award["agreement_id"] != agreement["id"]:
            continue
        if award["status"] not in ("PROVISIONAL", "FINAL"):
            continue
        award_cert = db.certifications.get(award["certification_id"])
        if award_cert is None or award_cert["student_id"] != certification["student_id"]:
            continue
        siblings.append(award)
    for award in by_created(siblings):
        spent += award["school_share_cents"]

    per_student_remaining_before = max(0, agreement["per_student_annual_cap_cents"] - spent)
    pool_remaining_before = agreement["pool_remaining_cents"]

    school_share = min(
        rhu(D(yr_gap) / 2),
        per_student_remaining_before,
        pool_remaining_before,
    )
    va_match = school_share
    out_of_pocket = max(0, yr_gap - school_share - va_match)
    return {
        "yr_gap_basis_cents": yr_gap,
        "per_student_remaining_before_cents": per_student_remaining_before,
        "pool_remaining_before_cents": pool_remaining_before,
        "school_share_cents": school_share,
        "va_match_cents": va_match,
        "student_out_of_pocket_cents": out_of_pocket,
    }


# =============================================================================
# CALC-4 — entitlement days charged
# =============================================================================
def calc4_calendar_full_term(certified_days, rop_tier_pct):
    return rhu(D(certified_days) * D(rop_tier_pct) / 100)


def calc4_prorated(days_before, old_tier_pct, days_after, new_tier_pct):
    return (rhu(D(days_before) * D(old_tier_pct) / 100)
            + rhu(D(days_after) * D(new_tier_pct) / 100))


# =============================================================================
# CALC-5 — change report lateness and liability
# =============================================================================
def calc5(reported_day, effective_day):
    days_late = days_between(effective_day, reported_day)
    reporting_status = "TIMELY" if days_late <= REPORTING_DEADLINE_DAYS else "LATE"
    liability_party = "STUDENT" if reporting_status == "TIMELY" else "SCHOOL"
    return days_late, reporting_status, liability_party


# =============================================================================
# CALC-6 — repayment waterfall (tuition bucket first, then housing)
# =============================================================================
def calc6_allocate(debt, amount_cents):
    applied_tuition = min(amount_cents,
                          debt["tuition_component_cents"] - debt["tuition_repaid_cents"])
    applied_mha = min(amount_cents - applied_tuition,
                      debt["mha_component_cents"] - debt["mha_repaid_cents"])
    return applied_tuition, applied_mha


# =============================================================================
# CALC-7 — 38 USC 3679(e) student protection predicate
# =============================================================================
def is_protected(student):
    if student["coe_status"] != "VERIFIED":
        return False
    protected_until = day_of(student, "protected_until")
    if protected_until is None or clock_day() > protected_until:
        return False
    for cert in db.certifications.values():
        if cert["student_id"] != student["id"]:
            continue
        if cert["status"] in ("CERTIFIED", "AMENDMENT_PENDING") and cert["tuition_payment_posted_on"] is None:
            return True
    return False


def refresh_protection(student):
    student["benefit_payment_protected"] = is_protected(student)
