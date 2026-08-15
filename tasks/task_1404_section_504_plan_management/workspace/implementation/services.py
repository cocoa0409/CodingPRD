"""Shared domain logic: lookups, audit ledger, derived fields, calculations.

Calculation rules implemented here (scaffold section 1.3):
  - implementation_compliance_ratio (trailing_30_day + cumulative_plan_year)
  - determination_timeliness_check (60-day window, whole days)
  - annual_review_window_check (365 days + 14-day grace for ANNUAL; strict for RE_EVALUATION)
  - re_evaluation_cadence_check (1095 days)
  - testing_accommodation_lead_time_check (>= 14 whole days)
  - staff_training_coverage_ratio (2dp half-up; empty staff -> 1.0)
  - school_posture_derivation (weighted composite, capped at 100)
  - teacher_ack_completion_gate
"""
from datetime import timedelta

from db import db, now, touch, create_audit_event
from errors import (raise_err, ERR_NOT_FOUND, ERR_SCHOOL_NOT_FOUND, ERR_STUDENT_NOT_FOUND,
                    ERR_STAFF_NOT_FOUND, ERR_REFERRAL_NOT_FOUND, ERR_EVALUATION_NOT_FOUND,
                    ERR_PLAN_NOT_FOUND, ERR_ACCOMMODATION_NOT_FOUND, ERR_ACK_NOT_FOUND,
                    ERR_REVIEW_NOT_FOUND, ERR_TESTING_REQUEST_NOT_FOUND,
                    ERR_GRIEVANCE_NOT_FOUND, ERR_TRAINING_RECORD_NOT_FOUND,
                    ERR_CONSENT_RECORD_NOT_FOUND, ERR_SCHOOL_UNDER_AUDIT_HOLD)
from util import days_between, dump, pct2

# ---------------------------------------------------------------------------
# Constants from the scaffold calculation tables
# ---------------------------------------------------------------------------
REFERRAL_REVIEW_WINDOW_DAYS = 15
DETERMINATION_WINDOW_DAYS = 60
ANNUAL_WINDOW_DAYS = 365
ANNUAL_GRACE_DAYS = 14
RE_EVAL_WINDOW_DAYS = 1095          # 3 * 365 (explicit constant)
TRAINING_VALIDITY_YEARS = 2         # 'exactly two years after trained_at' (calendar)
MIN_LEAD_DAYS = 14
TESTING_REVIEW_WINDOW_DAYS = 7
INFORMAL_RESOLUTION_WINDOW_DAYS = 30
FORMAL_RESOLUTION_WINDOW_DAYS = 60
TRAILING_WINDOW_DAYS = 30

GRIEVANCE_WEIGHT = 20
OCR_FLAG_WEIGHT = 50
OVERDUE_REVIEW_WEIGHT = 15
OVERDUE_REVIEW_CAP = 30
TRAINING_GAP_WEIGHT = 25
TRAINING_FLOOR = 0.95
PROBATION_THRESHOLD = 30
AUDIT_HOLD_THRESHOLD = 60

EVALUATION_OPEN_STATES = {"INITIATED", "CONSENT_PENDING", "CONSENT_RECEIVED", "EVALUATION_IN_PROGRESS"}
PLAN_OPEN_STATES_AT_CREATE = {"DRAFT", "PENDING_PARENT_CONSENT", "PENDING_TEACHER_ACK",
                              "ACTIVE", "UNDER_ANNUAL_REVIEW", "SUSPENDED"}
PLAN_BLOCKING_STATES_AT_SUBMIT = {"DRAFT", "PENDING_PARENT_CONSENT", "PENDING_TEACHER_ACK",
                                  "ACTIVE", "UNDER_ANNUAL_REVIEW"}
OPEN_GRIEVANCE_STATES = {"FILED", "INFORMAL_RESOLUTION", "FORMAL_INVESTIGATION"}

REVIEW_TYPES = {"ANNUAL", "RE_EVALUATION", "PARENT_REQUESTED", "DISTRICT_AUDIT"}
STAFF_ROLES = {"TEACHER", "COORDINATOR", "PRINCIPAL", "DISTRICT_DIRECTOR"}
DISABILITY_CATEGORIES = {"PHYSICAL", "MENTAL", "LEARNING", "CHRONIC_HEALTH", "OTHER"}
ACCOMMODATION_TYPES = {"EXTENDED_TIME", "PREFERENTIAL_SEATING", "REDUCED_WORKLOAD",
                       "BREAKS_AS_NEEDED", "ASSISTIVE_TECH", "MODIFIED_GRADING", "OTHER"}
TRAINING_TOPICS = {"SECTION_504_BASICS", "ACCOMMODATION_DELIVERY", "GRIEVANCE_PROCEDURES",
                   "TESTING_ACCOMMODATIONS", "TRANSITION_PROCEDURES"}
CONSENT_SCOPES = {"INITIAL_PLAN", "PLAN_AMENDMENT", "RE_EVALUATION", "EXIT_TO_IEP",
                  "TESTING_ACCOMMODATION"}
GRIEVANCE_CATEGORIES = {"DISCRIMINATION", "NON_IMPLEMENTATION", "PROCEDURAL_VIOLATION",
                        "RETALIATION", "OTHER"}
REVIEW_OUTCOMES = {"CONTINUE_PLAN", "MODIFY_PLAN", "EXIT_TO_IEP", "TERMINATE_504"}
DETERMINATION_OUTCOMES = {"ELIGIBLE", "NOT_ELIGIBLE"}
IEP_STATUSES = {"NONE", "IEP_ACTIVE", "IEP_EXITED"}


# ---------------------------------------------------------------------------
# Existence lookups (resource-specific 404s)
# ---------------------------------------------------------------------------
def _get(coll, rid, err_pair, label):
    rec = coll.get(rid) if isinstance(rid, str) else None
    if rec is None:
        raise_err(err_pair, f"{label} not found: {rid}")
    return rec


def get_school(rid):
    return _get(db.schools, rid, ERR_SCHOOL_NOT_FOUND, "School")


def get_student(rid):
    return _get(db.students, rid, ERR_STUDENT_NOT_FOUND, "Student")


def get_staff(rid):
    return _get(db.staff, rid, ERR_STAFF_NOT_FOUND, "StaffMember")


def get_referral(rid):
    return _get(db.referrals, rid, ERR_REFERRAL_NOT_FOUND, "Referral")


def get_evaluation(rid):
    return _get(db.evaluations, rid, ERR_EVALUATION_NOT_FOUND, "Evaluation")


def get_plan(rid):
    return _get(db.plans, rid, ERR_PLAN_NOT_FOUND, "Plan")


def get_accommodation(rid):
    return _get(db.accommodations, rid, ERR_ACCOMMODATION_NOT_FOUND, "Accommodation")


def get_ack(rid):
    return _get(db.acks, rid, ERR_ACK_NOT_FOUND, "TeacherAcknowledgment")


def get_review(rid):
    return _get(db.reviews, rid, ERR_REVIEW_NOT_FOUND, "ReviewEvent")


def get_testing_request(rid):
    return _get(db.testing_requests, rid, ERR_TESTING_REQUEST_NOT_FOUND, "TestingAccommodationRequest")


def get_consent(rid):
    return _get(db.consents, rid, ERR_CONSENT_RECORD_NOT_FOUND, "ParentConsentRecord")


def get_grievance(rid):
    return _get(db.grievances, rid, ERR_GRIEVANCE_NOT_FOUND, "Grievance")


def get_training_record(rid):
    return _get(db.training_records, rid, ERR_TRAINING_RECORD_NOT_FOUND, "StaffTrainingRecord")


def get_audit_event(rid):
    return _get(db.audit_events, rid, ERR_NOT_FOUND, "ComplianceAuditEvent")


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------
def school_of_student(student):
    return db.schools.get(student["school_id"])


def school_of_plan(plan):
    student = db.students.get(plan["student_id"])
    return school_of_student(student) if student else None


def school_of_evaluation(evaluation):
    student = db.students.get(evaluation["student_id"])
    return school_of_student(student) if student else None


def posture_gate(school):
    """Priority-4 gate: mutations under an AUDIT_HOLD school are rejected."""
    if school is not None and school.get("school_posture") == "AUDIT_HOLD":
        raise_err(ERR_SCHOOL_UNDER_AUDIT_HOLD,
                  f"School {school['id']} is under AUDIT_HOLD; mutations are blocked")


# ---------------------------------------------------------------------------
# Audit ledger
# ---------------------------------------------------------------------------
def emit(event_type, school_id, entity_ref, actor_staff_id, payload=None):
    return create_audit_event({
        "school_id": school_id,
        "event_type": event_type,
        "entity_ref": entity_ref,
        "actor_staff_id": actor_staff_id,
        "event_payload": payload or {},
    })


# ---------------------------------------------------------------------------
# Training currency / coverage (staff_training_coverage_ratio)
# ---------------------------------------------------------------------------
def latest_training_record(staff_id):
    records = [r for r in db.training_records.values() if r["staff_id"] == staff_id]
    if not records:
        return None
    return max(records, key=lambda r: (r["trained_at"], r["_seq"]))


def record_is_current(rec):
    return now() < rec["expires_at"]


def current_training_status(staff):
    latest = latest_training_record(staff["id"])
    if latest is None:
        return "UNTRAINED"
    return "TRAINED_CURRENT" if record_is_current(latest) else "TRAINED_EXPIRED"


def active_staff(school_id):
    return [s for s in db.staff.values()
            if s["school_id"] == school_id and s.get("is_active", True)]


def coverage_ratio(school_id):
    staff = active_staff(school_id)
    if not staff:
        return 1.0
    trained = sum(1 for s in staff if current_training_status(s) == "TRAINED_CURRENT")
    return trained / len(staff)


def coverage_pct(school_id):
    staff = active_staff(school_id)
    trained = sum(1 for s in staff if current_training_status(s) == "TRAINED_CURRENT")
    return pct2(trained, len(staff))


# ---------------------------------------------------------------------------
# School posture (school_posture_derivation)
# ---------------------------------------------------------------------------
def open_grievance_count(school_id):
    n = 0
    for gr in db.grievances.values():
        stu = db.students.get(gr["student_id"])
        if stu and stu["school_id"] == school_id and gr["grievance_status"] in OPEN_GRIEVANCE_STATES:
            n += 1
    return n


def ocr_escalation_flag(school_id):
    for gr in db.grievances.values():
        stu = db.students.get(gr["student_id"])
        if stu and stu["school_id"] == school_id and gr["grievance_status"] == "ESCALATED_TO_OCR":
            return 1
    return 0


def overdue_review_count(school_id):
    n = 0
    for rv in db.reviews.values():
        plan = db.plans.get(rv["plan_id"])
        stu = db.students.get(plan["student_id"]) if plan else None
        if stu and stu["school_id"] == school_id and rv["review_status"] == "OVERDUE":
            n += 1
    return n


def posture_components(school_id):
    og = open_grievance_count(school_id)
    ocr = ocr_escalation_flag(school_id)
    od = overdue_review_count(school_id)
    gap = 1 if coverage_ratio(school_id) < TRAINING_FLOOR else 0
    og_w = og * GRIEVANCE_WEIGHT
    ocr_w = ocr * OCR_FLAG_WEIGHT
    od_w = min(od * OVERDUE_REVIEW_WEIGHT, OVERDUE_REVIEW_CAP)
    gap_w = gap * TRAINING_GAP_WEIGHT
    score = min(og_w + ocr_w + od_w + gap_w, 100)
    if score >= AUDIT_HOLD_THRESHOLD or ocr_w > 0:
        posture = "AUDIT_HOLD"
    elif score >= PROBATION_THRESHOLD:
        posture = "PROBATION"
    else:
        posture = "OPERATIONAL"
    return posture, score, og, od


def recompute_posture(school, actor_staff_id=None):
    """Recompute stored posture; on change, bump school version and emit POSTURE_CHANGED."""
    if school is None:
        return
    posture, score, _, _ = posture_components(school["id"])
    if school.get("school_posture") != posture:
        old = school.get("school_posture")
        school["school_posture"] = posture
        touch(school)
        emit("POSTURE_CHANGED", school["id"], school["id"], actor_staff_id,
             {"from": old, "to": posture, "composite_score": score})


def recompute_posture_for_student(student, actor_staff_id=None):
    recompute_posture(school_of_student(student), actor_staff_id)


# ---------------------------------------------------------------------------
# Plans: compliance ratio, ack gate, active-plan derivation
# ---------------------------------------------------------------------------
def plan_logs(plan_id):
    return [l for l in db.logs.values() if l["plan_id"] == plan_id]


def compliance_trailing_30(plan_id):
    """Window W = [now - 30 days, now], inclusive both ends; empty -> 1.0 (100.0)."""
    lo = now() - timedelta(days=TRAILING_WINDOW_DAYS)
    hi = now()
    logs = [l for l in plan_logs(plan_id) if lo <= l["log_date"] <= hi]
    implemented = sum(1 for l in logs if l["was_implemented_as_planned"])
    return pct2(implemented, len(logs))


def plan_year_anchor(plan):
    """Later of plan_effective_date and the latest completed ANNUAL review's completed_at."""
    anchor = plan.get("plan_effective_date")
    for rv in db.reviews.values():
        if (rv["plan_id"] == plan["id"] and rv["review_type"] == "ANNUAL"
                and rv["review_status"] == "COMPLETED" and rv.get("completed_at")):
            if anchor is None or rv["completed_at"] > anchor:
                anchor = rv["completed_at"]
    return anchor


def compliance_cumulative(plan):
    anchor = plan_year_anchor(plan)
    logs = plan_logs(plan["id"])
    if anchor is not None:
        logs = [l for l in logs if l["log_date"] >= anchor]
    implemented = sum(1 for l in logs if l["was_implemented_as_planned"])
    return pct2(implemented, len(logs))


def plan_acks(plan_id):
    return [a for a in db.acks.values() if a["plan_id"] == plan_id]


def ack_gate_satisfied(plan_id):
    """True iff at least one ack row exists and none remain PENDING or DECLINED."""
    acks = plan_acks(plan_id)
    if not acks:
        return False
    pending = sum(1 for a in acks if a["ack_status"] == "PENDING")
    declined = sum(1 for a in acks if a["ack_status"] == "DECLINED")
    return pending == 0 and declined == 0


def has_active_plan(student_id):
    return sum(1 for p in db.plans.values()
               if p["student_id"] == student_id and p["plan_status"] == "ACTIVE") == 1


def annual_review_grace_delta(review_type):
    """Grace window for overdue flip / was_late: 14 days for ANNUAL, none otherwise."""
    return timedelta(days=ANNUAL_GRACE_DAYS) if review_type == "ANNUAL" else timedelta(0)


def reevaluation_due_anchor(student_id):
    """created_at of the most recent DETERMINATION_MADE evaluation for the student."""
    evals = [e for e in db.evaluations.values()
             if e["student_id"] == student_id and e["evaluation_status"] == "DETERMINATION_MADE"]
    if not evals:
        return None
    return max(evals, key=lambda e: (e["created_at"], e["_seq"]))["created_at"]


# ---------------------------------------------------------------------------
# Serializers (computed fields resolved live at read time)
# ---------------------------------------------------------------------------
def school_out(s):
    return dump(s)


def student_out(s):
    out = dump(s)
    out["has_active_504_plan"] = has_active_plan(s["id"])
    return out


def staff_out(s):
    out = dump(s)
    out["current_training_status"] = current_training_status(s)
    return out


def training_out(r):
    out = dump(r)
    out["training_status"] = "CURRENT" if record_is_current(r) else "EXPIRED"
    return out


def referral_out(r):
    return dump(r)


def evaluation_out(e):
    return dump(e)


def plan_out(p):
    out = dump(p)
    out["implementation_compliance_pct"] = compliance_trailing_30(p["id"])
    out["all_teachers_acknowledged"] = ack_gate_satisfied(p["id"])
    return out


def accommodation_out(a):
    return dump(a)


def ack_out(a):
    return dump(a)


def log_out(l):
    return dump(l)


def review_out(r):
    return dump(r)


def testing_out(t):
    return dump(t)


def consent_out(c):
    return dump(c)


def grievance_out(g):
    return dump(g)


def audit_event_out(e):
    return dump(e)
