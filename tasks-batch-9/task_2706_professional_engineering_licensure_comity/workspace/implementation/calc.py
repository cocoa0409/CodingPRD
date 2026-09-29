"""Every pinned calculation in the specification (PRD 2.8, 3.2, 3.3, 3.6, 3.9)."""
from decimal import Decimal

import db
from util import (add_days, add_months, ceil_int, dec, floor_int, month_index,
                  round_half_up, round_half_up_int)

# ------------------------------------------------------------------ fee schedule
BASE_FEE = {"STANDARD_EXAM": 25000, "COMITY": 37500}
PER_RECORD_VERIFICATION_FEE = 2500
NCEES_RECORD_FEE = 7500
EXPEDITE_RATE = Decimal("0.18")

SINGLE_BLOCK_CAP_MONTHS = 48
PROGRAMME_CAP_MONTHS = 96
RESPONSIBILITY_WEIGHT = {
    "RESPONSIBLE_CHARGE": Decimal("1.00"),
    "PROGRESSIVE": Decimal("0.75"),
    "SUBORDINATE": Decimal("0.50"),
}
RELATIONSHIP_WEIGHT = {
    "DIRECT_SUPERVISOR": Decimal("1.00"),
    "PROJECT_MANAGER": Decimal("0.50"),
    "PEER": Decimal("0.50"),
}
PROVISIONAL_STATUSES = ("UNVERIFIED", "PENDING_VERIFICATION", "VERIFIED", "DISPUTED")

PDH_CATEGORY_CAP = {
    "COURSE": Decimal("30"),
    "SEMINAR": Decimal("30"),
    "TEACHING": Decimal("10"),
    "PUBLICATION": Decimal("10"),
    "PATENT": Decimal("10"),
}
SELF_STUDY_CAP_SELF_CERTIFIED = Decimal("8")
SELF_STUDY_CAP_AUDIT = Decimal("0")
CARRYOVER_CAP = Decimal("15")
ETHICS_FLOOR_HOURS = Decimal("2")

PENALTY_BASE = {
    "NEGLIGENCE": 150000,
    "UNLICENSED_PRACTICE": 250000,
    "PLAN_STAMPING": 200000,
    "CPC_FRAUD": 100000,
}
STAMPING_PER_SHEET = 1725
COST_RECOVERY_BASE = 48000
PENALTY_CAP = 1000000

BIENNIUM_MONTHS = 24
RENEWAL_WINDOW_DAYS = 90
REINSTATEMENT_GRACE_DAYS = 730
AUTHORIZATION_VALID_DAYS = 365
RETAKE_WAIT_DAYS = 90
DEFICIENCY_RESPONSE_DAYS = 30
FIRM_REGISTRATION_DAYS = 365
EXAM_WINDOW_MINUTES = 480
SEAT_TURNOVER_BUFFER_MINUTES = 45
MAX_ATTEMPTS = 3
MAX_DEFICIENCY_CYCLES = 3
PASSING_SCORE = 70
REQUIRED_EXPERIENCE_MONTHS = 48
COMITY_MIN_YEARS_LICENSED = 4
MIN_MAKEUP_PDH = Decimal("15")
MIN_REINSTATEMENT_FEE_CENTS = 45000
DEFAULT_PDH_REQUIREMENT = Decimal("30")


# --------------------------------------------------------------- child lookups
def records_of(application_id):
    return [r for r in db.all_rows("experience_records")
            if r["application_id"] == application_id]


def references_of(experience_record_id):
    return [r for r in db.all_rows("references")
            if r["experience_record_id"] == experience_record_id]


def references_of_application(application_id):
    ids = {r["id"] for r in records_of(application_id)}
    return [r for r in db.all_rows("references") if r["experience_record_id"] in ids]


def authorizations_of(application_id):
    return [a for a in db.all_rows("exam_authorizations")
            if a["application_id"] == application_id]


def appointments_of_authorization(authorization_id):
    return [a for a in db.all_rows("exam_appointments")
            if a["exam_authorization_id"] == authorization_id]


def pdh_records_of(report_id):
    return [p for p in db.all_rows("pdh_records") if p["cpc_report_id"] == report_id]


# ------------------------------------------------------------- fee assessment
def fee_assessment(application):
    pathway = application["pathway"]
    base = BASE_FEE[pathway]
    record_count = len(records_of(application["id"]))
    records_fee = PER_RECORD_VERIFICATION_FEE * record_count
    ncees_fee = NCEES_RECORD_FEE if application["ncees_record_status"] == "MATCHED" else 0
    subtotal = base + records_fee + ncees_fee
    if application["expedite_requested"]:
        expedite = round_half_up_int(EXPEDITE_RATE * subtotal)
    else:
        expedite = 0
    pre_credit_total = subtotal + expedite
    if pathway != "COMITY":
        tier = Decimal("0.00")
    elif pre_credit_total >= 50000:
        tier = Decimal("0.15")
    elif pre_credit_total >= 30000:
        tier = Decimal("0.10")
    else:
        tier = Decimal("0.05")
    credit = round_half_up_int(tier * pre_credit_total)
    total = pre_credit_total - credit
    return {
        "base_fee_cents": base,
        "records_verification_fee_cents": records_fee,
        "ncees_record_fee_cents": ncees_fee,
        "expedite_surcharge_cents": expedite,
        "pre_credit_total_cents": pre_credit_total,
        "comity_credit_tier_pct": tier,
        "comity_credit_cents": credit,
        "assessment_total_cents": total,
    }


def reassess_fee(application):
    """Recompute and store fee_assessment_cents (never after the freeze)."""
    total = fee_assessment(application)["assessment_total_cents"]
    db.write(application, fee_assessment_cents=total)
    return total


# --------------------------------------------------------- experience credit
def raw_months(record):
    return month_index(record["period_end_month"]) - month_index(
        record["period_start_month"]) + 1


def credit_multiplier(record):
    responsibility = RESPONSIBILITY_WEIGHT[record["responsibility_level"]]
    degree = Decimal("1.00") if record["post_degree"] else Decimal("0.50")
    return round_half_up(responsibility * degree, 2)


def accepted_reference(record):
    for ref in references_of(record["id"]):
        if ref["status"] == "ACCEPTED":
            return ref
    return None


def _variant_weight(record, variant):
    if variant == "provisional":
        return Decimal("1.00")
    ref = accepted_reference(record)
    if ref is None:
        return Decimal("1.00")
    return RELATIONSHIP_WEIGHT.get(ref["relationship"], Decimal("1.00"))


def _included(record, variant):
    status = record["verification_status"]
    if variant == "provisional":
        return status in PROVISIONAL_STATUSES
    return status == "VERIFIED"


def aggregate_credit(application, variant):
    """Returns (total_months, {record_id: contribution}) for the given variant."""
    contributions = {}
    total = 0
    for record in records_of(application["id"]):
        if not _included(record, variant):
            contributions[record["id"]] = 0
            continue
        truncated = floor_int(dec(raw_months(record)) * credit_multiplier(record))
        capped = min(truncated, SINGLE_BLOCK_CAP_MONTHS)
        contribution = floor_int(dec(capped) * _variant_weight(record, variant))
        contributions[record["id"]] = contribution
        total += contribution
    return min(total, PROGRAMME_CAP_MONTHS), contributions


def recompute_provisional(application):
    total, _ = aggregate_credit(application, "provisional")
    db.write(application, provisional_experience_months=total)
    return total


def recompute_verified(application):
    total, contributions = aggregate_credit(application, "verified")
    for record in records_of(application["id"]):
        db.write(record, credited_months=contributions.get(record["id"], 0))
    db.write(application, verified_experience_months=total)
    return total


def refresh_record_derived(record):
    db.write(record, raw_months=raw_months(record),
             credit_multiplier=credit_multiplier(record))


def months_overlap(a_start, a_end, b_start, b_end):
    """Closed inclusive month intervals share at least one month."""
    return (month_index(a_start) <= month_index(b_end)
            and month_index(b_start) <= month_index(a_end))


# ------------------------------------------------------------ competency hours
def _pdh_included(record, context):
    status = record["documentation_status"]
    if context == "self_certified":
        return status in ("NONE", "ACCEPTED")
    return status == "ACCEPTED"


def pdh_total(report, context):
    items = [p for p in pdh_records_of(report["id"]) if _pdh_included(p, context)]
    caps = dict(PDH_CATEGORY_CAP)
    caps["SELF_STUDY"] = (SELF_STUDY_CAP_SELF_CERTIFIED if context == "self_certified"
                          else SELF_STUDY_CAP_AUDIT)
    activity_subtotal = Decimal("0")
    for category in ("COURSE", "SEMINAR", "TEACHING", "PUBLICATION", "PATENT",
                     "SELF_STUDY"):
        summed = sum((dec(p["pdh_hours"]) for p in items if p["activity_type"] == category),
                     Decimal("0"))
        activity_subtotal += min(summed, caps[category])
    carryover = min(dec(report["carryover_pdh_claimed"]), CARRYOVER_CAP)
    return round_half_up(activity_subtotal + carryover, 1)


def pdh_shortfall(report, context, pdh_requirement):
    total = pdh_total(report, context)
    items = [p for p in pdh_records_of(report["id"]) if _pdh_included(p, context)]
    ethics_hours = sum((dec(p["pdh_hours"]) for p in items if p["ethics_flag"]),
                       Decimal("0"))
    hour_deficit = max(Decimal("0"), dec(pdh_requirement) - total)
    ethics_deficit = max(Decimal("0"), ETHICS_FLOOR_HOURS - ethics_hours)
    return round_half_up(hour_deficit + ethics_deficit, 1)


SELF_CERT_CONTEXT_STATUSES = ("SUBMITTED", "ACCEPTED")
AUDIT_CONTEXT_STATUSES = ("UNDER_AUDIT", "AUDIT_CLEARED", "AUDIT_DEFICIENT")


def refresh_report(report, force_audit=False):
    """Rewrite the totals for whichever context matches the report's status."""
    license_row = db.get("licenses", report["license_id"])
    requirement = license_row["pdh_requirement"] if license_row else Decimal("0")
    status = report["status"]
    if force_audit:
        db.write(report, audit_verified_total_pdh=pdh_total(report, "audit_verified"))
    if status in SELF_CERT_CONTEXT_STATUSES:
        db.write(report,
                 self_certified_total_pdh=pdh_total(report, "self_certified"),
                 shortfall_pdh=pdh_shortfall(report, "self_certified", requirement))
    elif status in AUDIT_CONTEXT_STATUSES:
        db.write(report,
                 audit_verified_total_pdh=pdh_total(report, "audit_verified"),
                 shortfall_pdh=pdh_shortfall(report, "audit_verified", requirement))
    return report


# ---------------------------------------------------------------- civil penalty
def penalty_factor(aggravating, mitigating):
    raw = Decimal("1.00") + Decimal("0.25") * aggravating - Decimal("0.15") * mitigating
    rounded = round_half_up(raw, 2)
    return min(max(rounded, Decimal("0.50")), Decimal("2.00"))


def assess_penalty(case):
    factor = penalty_factor(case["aggravating_factor_count"],
                            case["mitigating_factor_count"])
    base = PENALTY_BASE[case["allegation_type"]]
    conduct = round_half_up_int(dec(base) * factor) * case["violation_count"]
    stamping = 0
    if case["subject_plan_submission_id"]:
        plan = db.get("plan_submissions", case["subject_plan_submission_id"])
        if plan is not None:
            stamping = round_half_up_int(dec(STAMPING_PER_SHEET) * factor) * plan["sheet_count"]
    cost_recovery = round_half_up_int(dec(COST_RECOVERY_BASE) * factor)
    total = min(conduct + stamping + cost_recovery, PENALTY_CAP)
    return factor, total


# ------------------------------------------------------------- licence periods
def lay_down_period(license_row, period_start):
    period_end = add_months(period_start, BIENNIUM_MONTHS)
    license_row["current_period_start"] = period_start
    license_row["current_period_end"] = period_end
    license_row["renewal_window_opens_at"] = add_days(period_end, -RENEWAL_WINDOW_DAYS)


# ------------------------------------------------------------------ seat ledger
def seat_conflict(existing, window_start, window_end):
    """Half-open minute intervals with an asymmetric 45 minute trailing buffer."""
    from util import add_minutes
    existing_buffered_end = add_minutes(existing["window_end"],
                                        SEAT_TURNOVER_BUFFER_MINUTES)
    new_buffered_end = add_minutes(window_end, SEAT_TURNOVER_BUFFER_MINUTES)
    return (window_start < existing_buffered_end
            and new_buffered_end > existing["window_start"])


def refresh_seat_ledger(center):
    committed = sum(1 for a in db.all_rows("exam_appointments")
                    if a["test_center_id"] == center["id"] and a["status"] == "SCHEDULED")
    db.write(center, seats_committed=committed,
             seats_available=center["seat_count"] - committed)


# --------------------------------------------------------------- audit sampling
def sampled_count(pool_size, sample_pct):
    return min(pool_size, max(1, ceil_int(dec(pool_size) * dec(sample_pct))))
