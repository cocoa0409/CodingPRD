"""Business calculations and clock-driven transitions (scaffold §1.3, PRD §3)."""
import re
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, touch

SEVERITY_BP = {"LOW": 2500, "MODERATE": 5000, "HIGH": 7500, "CRITICAL": 10000}
MAX_SCORE_BP = 100000
OVERDUE_SURCHARGE_BP_PER_DAY = 25
OVERDUE_SURCHARGE_CAP_BP = 5000
FROZEN_ITEM_THRESHOLD = 3
BUSINESS_DAY_COUNT = 10

FORWARD_STATUSES = {"OPEN", "REMEDIATION_PLANNED", "IN_PROGRESS", "OVERDUE",
                    "VALIDATION_SUBMITTED"}
HISTORICAL_STATUSES = {"CLOSED", "OVERDUE", "VALIDATION_SUBMITTED"}


# ---------------------------------------------------------------- dates
def first_day_due(start_dt):
    """Ten business days from scheduled_start_date; start counts as day 1 when
    it is itself a business day, otherwise the next Monday is day 1 (PRD §3.2)."""
    d = start_dt.date()
    while d.weekday() >= 5:  # Sat/Sun -> next business day
        d += timedelta(days=1)
    count = 1
    while count < BUSINESS_DAY_COUNT:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return d


def _day(d):
    return d.date() if hasattr(d, "date") else d


# ------------------------------------------------------------- repeat refs
def normalize_ref(ref):
    """Strip whitespace, uppercase, drop trailing "-R<n>" suffix."""
    return re.sub(r"-R\d+$", "", ref.strip().upper())


def detect_repeat(issue_ref, exam, created_at):
    """True iff a different CLOSED issue on any examination of the same agency
    shares the normalized ref and closed strictly before created_at."""
    norm = normalize_ref(issue_ref)
    for other in db.issues.values():
        if other["status"] != "CLOSED" or other["closed_at"] is None:
            continue
        if not other["closed_at"] < created_at:
            continue
        oexam = db.exams.get(other["examination_id"])
        if oexam is None or oexam["agency_id"] != exam["agency_id"]:
            continue
        if normalize_ref(other["issue_ref"]) == norm:
            return True
    return False


# ---------------------------------------------------------------- risk
def _contribution(issue, mult_bp):
    base = SEVERITY_BP[issue["severity"]]
    if issue["is_repeat_finding"]:
        base = int(
            (Decimal(base) * Decimal(mult_bp) / Decimal(10000)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP)
        )
    return base


def risk_forward(exam):
    """Forward-looking variant: non-CLOSED issues plus per-day OVERDUE
    surcharge; capped at 100000 bp (PRD §3.5)."""
    agency = db.agencies.get(exam["agency_id"])
    mult = agency["repeat_finding_multiplier_bp"] if agency else 10000
    today = db.clock.date()
    total = 0
    for iss in db.issues.values():
        if iss["examination_id"] != exam["id"] or iss["status"] not in FORWARD_STATUSES:
            continue
        c = _contribution(iss, mult)
        if iss["status"] == "OVERDUE":
            days = max(0, (today - _day(iss["due_date"])).days)
            c += min(days * OVERDUE_SURCHARGE_BP_PER_DAY, OVERDUE_SURCHARGE_CAP_BP)
        total += c
    return min(total, MAX_SCORE_BP)


def risk_historical(exam):
    """Historical variant: CLOSED/OVERDUE/VALIDATION_SUBMITTED, no surcharge.
    Returns (score_bp, contributing_issue_ids)."""
    agency = db.agencies.get(exam["agency_id"])
    mult = agency["repeat_finding_multiplier_bp"] if agency else 10000
    rows = [i for i in db.issues.values()
            if i["examination_id"] == exam["id"] and i["status"] in HISTORICAL_STATUSES]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = 0
    ids = []
    for iss in rows:
        total += _contribution(iss, mult)
        ids.append(iss["id"])
    return min(total, MAX_SCORE_BP), ids


# ------------------------------------------------------- posture & counts
def count_overdue_items(exam_id):
    today = db.clock.date()
    return sum(
        1 for it in db.items.values()
        if it["examination_id"] == exam_id
        and it["status"] == "PENDING"
        and _day(it["due_date"]) < today
    )


def compute_posture(exam):
    """FROZEN when >=3 overdue items or longest issue-overdue stretch reaches
    the agency escalation threshold; else RESTRICTED on any overdue item or
    any OVERDUE milestone beneath the exam; else NORMAL (PRD §3.8)."""
    agency = db.agencies.get(exam["agency_id"])
    threshold = agency["escalation_threshold_days"] if agency else 730
    today = db.clock.date()
    max_days = 0
    issue_ids = set()
    for iss in db.issues.values():
        if iss["examination_id"] != exam["id"]:
            continue
        issue_ids.add(iss["id"])
        if iss["status"] == "OVERDUE":
            max_days = max(max_days, max(0, (today - _day(iss["due_date"])).days))
    any_ms_overdue = False
    if issue_ids:
        plan_ids = {p["id"] for p in db.plans.values() if p["issue_id"] in issue_ids}
        any_ms_overdue = any(
            m["remediation_plan_id"] in plan_ids and m["status"] == "OVERDUE"
            for m in db.milestones.values()
        )
    if exam["overdue_item_count"] >= FROZEN_ITEM_THRESHOLD or max_days >= threshold:
        return "FROZEN"
    if exam["overdue_item_count"] >= 1 or any_ms_overdue:
        return "RESTRICTED"
    return "NORMAL"


def recompute_exam(exam):
    """Recompute the derived fields. Never bumps version — callers' side
    effects own version accounting."""
    exam["overdue_item_count"] = count_overdue_items(exam["id"])
    exam["posture"] = compute_posture(exam)
    exam["repeat_finding_risk_score_bp"] = risk_forward(exam)


# ------------------------------------------------------- auto transitions
def maybe_advance_exam(exam):
    """REMEDIATION -> VALIDATION once >=1 issue exists and every issue stands
    VALIDATION_SUBMITTED or CLOSED."""
    if exam["status"] != "REMEDIATION":
        return
    issues = [i for i in db.issues.values() if i["examination_id"] == exam["id"]]
    if not issues:
        return
    if all(i["status"] in ("VALIDATION_SUBMITTED", "CLOSED") for i in issues):
        exam["status"] = "VALIDATION"
        touch(exam)


def process_clock(new_dt):
    """Advance the logical clock; fire clock-driven transitions (PRD §3.8)."""
    db.clock = new_dt
    today = new_dt.date()
    affected_exams = set()

    def exam_of_issue(iss):
        return db.exams.get(iss["examination_id"])

    def agency_of(exam):
        return db.agencies.get(exam["agency_id"]) if exam else None

    # Milestones: PENDING/IN_PROGRESS whose due date is strictly past -> OVERDUE
    for ms in db.milestones.values():
        if ms["status"] in ("PENDING", "IN_PROGRESS") and _day(ms["due_date"]) < today:
            ms["status"] = "OVERDUE"
            touch(ms)
            plan = db.plans.get(ms["remediation_plan_id"])
            if plan:
                iss = db.issues.get(plan["issue_id"])
                if iss:
                    affected_exams.add(iss["examination_id"])

    # Issues: OPEN/REMEDIATION_PLANNED/IN_PROGRESS past due -> OVERDUE
    for iss in db.issues.values():
        if iss["status"] in ("OPEN", "REMEDIATION_PLANNED", "IN_PROGRESS") \
                and _day(iss["due_date"]) < today:
            iss["status"] = "OVERDUE"
            touch(iss)
            exam = exam_of_issue(iss)
            agency = agency_of(exam)
            days = max(0, (today - _day(iss["due_date"])).days)
            if iss["is_repeat_finding"] or (
                    agency and days >= agency["escalation_threshold_days"]):
                iss["escalated_to_board"] = True
            affected_exams.add(iss["examination_id"])
        elif iss["status"] == "OVERDUE" and not iss["escalated_to_board"]:
            exam = exam_of_issue(iss)
            agency = agency_of(exam)
            days = max(0, (today - _day(iss["due_date"])).days)
            if iss["is_repeat_finding"] or (
                    agency and days >= agency["escalation_threshold_days"]):
                iss["escalated_to_board"] = True
                touch(iss)

    for exam in db.exams.values():
        recompute_exam(exam)
    for ex_id in affected_exams:
        exam = db.exams.get(ex_id)
        if exam is not None:
            touch(exam)
