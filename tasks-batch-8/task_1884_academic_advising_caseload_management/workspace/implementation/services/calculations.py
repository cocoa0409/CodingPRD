"""Calculation rules from scaffold Table 1.3 — caseload, risk, clearance, mapping, SLA, queue."""
from datetime import timedelta

import db
from services.common import parse_iso_datetime

# --- Constants from scaffold calculations.constants ---
RISK_WEIGHT = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
SEVERITY_BOOST = {"HIGH": 20, "MEDIUM": 12, "LOW": 6}
SLA_DAYS = {"HIGH": 2, "MEDIUM": 5, "LOW": 10}
NO_SHOW_CAP = 3
INTERVENTION_WEIGHT = 10
HOLD_WEIGHT = 8
TIER_HIGH_MIN = 70
TIER_MEDIUM_MIN = 40
MAX_SCORE = 100
MAX_TERM_CREDITS = 18
DROPIN_MAX_ACTIVE_TICKETS = 3
MAX_ATTEMPTS = 3


# ---------------------------------------------------------------- caseload_load
def recompute_advisor_loads(advisor_id):
    """Recompute assigned_active_count and weighted_load for one advisor."""
    advisor = db.advisors.get(advisor_id)
    if not advisor:
        return
    active = [a for a in db.assignments.values()
              if a["advisor_id"] == advisor_id and a["status"] == "ACTIVE"]
    advisor["assigned_active_count"] = len(active)
    total = 0
    for asg in active:
        student = db.students.get(asg["student_id"])
        if student:
            total += RISK_WEIGHT.get(student.get("risk_tier", "LOW"), 1)
    advisor["weighted_load"] = total


def recompute_advisor_scheduled_minutes(advisor_id):
    """Recompute scheduled_minutes: sum duration_minutes over SCHEDULED/CHECKED_IN appointments."""
    advisor = db.advisors.get(advisor_id)
    if not advisor:
        return
    total = 0
    for appt in db.appointments.values():
        if appt["advisor_id"] == advisor_id and appt["status"] in ("SCHEDULED", "CHECKED_IN"):
            total += appt.get("duration_minutes", 0)
    advisor["scheduled_minutes"] = total


def recompute_all_advisor_metrics(advisor_id):
    recompute_advisor_loads(advisor_id)
    recompute_advisor_scheduled_minutes(advisor_id)


# ---------------------------------------------------------------- at_risk_score
def compute_at_risk_score(student_id):
    """Compute the student's at_risk_score per calculations.at_risk_score."""
    student = db.students[student_id]
    gpa = student.get("gpa", 4.0)
    if gpa < 2.0:
        base = 40
    elif gpa < 2.5:
        base = 25
    else:
        base = 10

    # referral boost: max severity boost among referrals in working/escalated states
    boost = 0
    for ref in db.referrals.values():
        if ref["student_id"] == student_id and ref["status"] in (
                "OPEN", "OUTREACH_IN_PROGRESS", "NO_RESPONSE", "ESCALATED"):
            boost = max(boost, SEVERITY_BOOST.get(ref["severity"], 0))

    no_show_points = 10 * min(student.get("no_show_count", 0), NO_SHOW_CAP)

    intervention_points = INTERVENTION_WEIGHT * sum(
        1 for i in db.interventions.values()
        if i["student_id"] == student_id and i["status"] == "OPEN")

    hold_points = HOLD_WEIGHT * sum(
        1 for h in db.holds.values()
        if h["student_id"] == student_id and h["status"] == "ACTIVE")

    score = base + boost + no_show_points + intervention_points + hold_points
    return min(score, MAX_SCORE)


def risk_tier_for(score):
    if score >= TIER_HIGH_MIN:
        return "HIGH"
    if score >= TIER_MEDIUM_MIN:
        return "MEDIUM"
    return "LOW"


def compute_advising_requirement_status(student):
    """Per calculations.advising_requirement."""
    if not student.get("advising_required_flag", False):
        return "NOT_REQUIRED"
    current_term = student.get("current_term_code")
    for appt in db.appointments.values():
        if (appt["student_id"] == student["id"]
                and appt["status"] == "COMPLETED"
                and appt["term_code"] == current_term):
            return "SATISFIED"
    return "REQUIRED"


def compute_registration_clearance(student):
    """Per calculations.registration_clearance."""
    for h in db.holds.values():
        if h["student_id"] == student["id"] and h["status"] == "ACTIVE":
            return "BLOCKED"
    if student.get("advising_requirement_status") == "REQUIRED":
        return "BLOCKED"
    return "CLEARED"


def recompute_student_risk(student_id, allow_high_flag=True):
    """Recompute at_risk_score and risk_tier; on HIGH flip set advising_required_flag
    and recompute requirement + clearance; recompute assigned advisor weighted_load.

    Returns True if tier changed to HIGH during this recompute.
    """
    student = db.students.get(student_id)
    if not student:
        return False
    old_tier = student.get("risk_tier")
    score = compute_at_risk_score(student_id)
    new_tier = risk_tier_for(score)
    student["at_risk_score"] = score
    student["risk_tier"] = new_tier
    became_high = (new_tier == "HIGH" and old_tier != "HIGH")
    if became_high and allow_high_flag:
        student["advising_required_flag"] = True
    student["advising_requirement_status"] = compute_advising_requirement_status(student)
    student["registration_clearance"] = compute_registration_clearance(student)
    # assigned advisor weighted_load recompute when tier changed
    if old_tier != new_tier:
        advisor_id = get_assigned_advisor_id(student_id)
        if advisor_id:
            recompute_advisor_loads(advisor_id)
    return became_high


def recompute_student_requirement_and_clearance(student_id):
    student = db.students.get(student_id)
    if not student:
        return
    student["advising_requirement_status"] = compute_advising_requirement_status(student)
    student["registration_clearance"] = compute_registration_clearance(student)


def get_assigned_advisor_id(student_id):
    """Return advisor_id of the student's ACTIVE assignment, or None."""
    for asg in db.assignments.values():
        if asg["student_id"] == student_id and asg["status"] == "ACTIVE":
            return asg["advisor_id"]
    return None


# ---------------------------------------------------------------- term_credit_mapping
def round_half_up_int(x):
    """ROUND_HALF_UP to integer for a non-negative float/Decimal-like value."""
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_term_credits(terms):
    """Return (per_term_rounded_list, mapped_credits_total) per calculations.term_credit_mapping.
    Pinned order: round each term first, then sum."""
    per_term = []
    total = 0
    for term in (terms or []):
        term_sum = 0.0
        for course in (term.get("courses") or []):
            credits = course.get("credits", 0)
            term_sum += float(credits)
        rounded = round_half_up_int(term_sum)
        per_term.append(rounded)
        total += rounded
    return per_term, total


# ---------------------------------------------------------------- outreach_sla_due_at
def compute_due_at(created_at_iso, severity):
    """due_at = created_at + SLA_DAYS[severity], second precision ISO 8601."""
    created = parse_iso_datetime(created_at_iso)
    days = SLA_DAYS.get(severity, 10)
    due = created + timedelta(days=days)
    # second precision
    due = due.replace(microsecond=0)
    return due.strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_is_sla_breached(referral, logical_now_iso):
    """is_sla_breached = (now > due_at strictly) AND status NOT IN {RESPONDED, CLOSED}."""
    if referral["status"] in ("RESPONDED", "CLOSED"):
        return False
    now = parse_iso_datetime(logical_now_iso)
    due = parse_iso_datetime(referral["due_at"])
    return now > due
