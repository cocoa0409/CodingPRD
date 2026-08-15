"""Business logic: calculations (SCAFFOLD §1.3 / PRD §3), derived-field
reconciliation, cascade side effects, and the logical-clock sweep pipeline
(PRD §2.5).
"""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import clock_date, parse_date, stamp_new, touch, new_id, add_months

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
FRESHNESS_WINDOW_DAYS = 183
UG_MIN = 12
GR_MIN = 9
ACADEMIC_FLOOR_ABSOLUTE = 3
MEDICAL_CUMULATIVE_MONTHS_MAX = 12
ADD_DROP_DAYS = 14
REGISTRATION_WINDOW_DAYS = 30
RECORD_GRACE_DAYS = 60
OPT_POST_START_WINDOW_DAYS = 60
OPT_FILE_BEFORE_DAYS = 90
OPT_FILE_AFTER_DAYS = 60
UNEMPLOYMENT_LIMIT_DAYS = 90
UNEMPLOYMENT_WARNING_DAYS = 75
ADDRESS_REPORT_WINDOW_DAYS = 10
VALIDITY_MONTHS_ENROLLED = 12
VALIDITY_MONTHS_OPT = 6
DAYS_PER_MONTH = 30
MONTHS_PER_YEAR = 12


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def record_of_student(student_id):
    """The student's single SevisRecord (1:1), or None."""
    for rec in db.sevis_records.values():
        if rec["student_id"] == student_id:
            return rec
    return None


def enrollments_of_student(student_id):
    return [e for e in db.term_enrollments.values() if e["student_id"] == student_id]


def authorizations_of_student(student_id):
    return [a for a in db.employment_authorizations.values() if a["student_id"] == student_id]


def periods_of_authorization(auth_id):
    return [p for p in db.employment_periods.values() if p["authorization_id"] == auth_id]


def endorsements_of_form(form_id):
    return [t for t in db.travel_endorsements.values() if t["i20_form_id"] == form_id]


def issued_forms_of_record(record_id):
    return [f for f in db.i20_forms.values()
            if f["sevis_record_id"] == record_id and f["status"] == "ISSUED"]


def issued_forms_of_student(student_id):
    return [f for f in db.i20_forms.values()
            if f["student_id"] == student_id and f["status"] == "ISSUED"]


# ---------------------------------------------------------------------------
# financial_coverage (PRD §3.1/§3.2): 183-day freshness window ending on the
# clock date; both bounds inclusive.
# ---------------------------------------------------------------------------

def _doc_is_fresh(doc, today):
    issue = parse_date(doc["issue_date"])
    return (today - timedelta(days=FRESHNESS_WINDOW_DAYS)) <= issue <= today


def funding_cents(student_id, today=None):
    """Return (verified_funding_cents, provisional_funding_cents) over the
    student's fresh financial documents."""
    if today is None:
        today = clock_date()
    verified = 0
    provisional = 0
    for doc in db.financial_documents.values():
        if doc["student_id"] != student_id:
            continue
        if not _doc_is_fresh(doc, today):
            continue
        if doc["status"] == "VERIFIED":
            verified += doc["amount_usd_cents"]
            provisional += doc["amount_usd_cents"]
        elif doc["status"] == "SUBMITTED":
            provisional += doc["amount_usd_cents"]
    return verified, provisional


# ---------------------------------------------------------------------------
# full_time_requirement (PRD §3.3/§3.4)
# ---------------------------------------------------------------------------

def base_min_credits(student):
    return UG_MIN if student["degree_level"] == "UNDERGRADUATE" else GR_MIN


def approved_rcl_of(enrollment_id):
    for rcl in db.reduced_course_loads.values():
        if rcl["enrollment_id"] == enrollment_id and rcl["status"] == "APPROVED":
            return rcl
    return None


def academic_floor(base_min):
    return max(ACADEMIC_FLOOR_ABSOLUTE, base_min // 2)


def effective_min_credits(enrollment):
    student = db.students.get(enrollment["student_id"])
    base = base_min_credits(student)
    rcl = approved_rcl_of(enrollment["id"])
    if rcl is None:
        return base
    if rcl["reason_category"] == "ACADEMIC":
        return academic_floor(base)
    if rcl["reason_category"] == "MEDICAL":
        return rcl["requested_credits"]
    # FINAL_TERM
    return max(1, rcl["requested_credits"])


# ---------------------------------------------------------------------------
# unemployment_days (PRD §3.5): settled (horizon yesterday) and as-of
# (horizon today) variants. Only computed for OPT_POST in APPROVED or
# COMPLETED status; every other status reports zero counters.
# ---------------------------------------------------------------------------

def _covered_days(auth, horizon):
    """Cardinality of the union of employment-period day spans clipped to
    [authorization.start_date, horizon]; ongoing periods run to the horizon."""
    start = parse_date(auth["start_date"])
    intervals = []
    for p in periods_of_authorization(auth["id"]):
        ps = parse_date(p["start_date"])
        pe = parse_date(p["end_date"]) if p["end_date"] else horizon
        lo = max(ps, start)
        hi = min(pe, horizon)
        if lo <= hi:
            intervals.append((lo, hi))
    intervals.sort()
    total = 0
    cur_lo = cur_hi = None
    one_day = timedelta(days=1)
    for lo, hi in intervals:
        if cur_lo is None:
            cur_lo, cur_hi = lo, hi
        elif lo <= cur_hi + one_day:
            if hi > cur_hi:
                cur_hi = hi
        else:
            total += (cur_hi - cur_lo).days + 1
            cur_lo, cur_hi = lo, hi
    if cur_lo is not None:
        total += (cur_hi - cur_lo).days + 1
    return total


def _unemployment_at_horizon(auth, horizon):
    start = parse_date(auth["start_date"])
    if horizon < start:
        elapsed = 0
    else:
        elapsed = (horizon - start).days + 1
    covered = _covered_days(auth, horizon)
    return elapsed - covered


def unemployment_counters(auth, today=None):
    """(settled, as_of) for an OPT_POST authorization in APPROVED or later;
    zeros otherwise."""
    if today is None:
        today = clock_date()
    if auth["auth_type"] != "OPT_POST" or auth["status"] not in ("APPROVED", "COMPLETED"):
        return 0, 0
    settled = _unemployment_at_horizon(auth, today - timedelta(days=1))
    as_of = _unemployment_at_horizon(auth, today)
    return settled, as_of


# ---------------------------------------------------------------------------
# travel_endorsement_validity (PRD §3.6)
# ---------------------------------------------------------------------------

def endorsement_valid_months(student_id):
    for auth in authorizations_of_student(student_id):
        if auth["auth_type"] == "OPT_POST" and auth["status"] in ("APPROVED", "COMPLETED"):
            return VALIDITY_MONTHS_OPT
    return VALIDITY_MONTHS_ENROLLED


# ---------------------------------------------------------------------------
# compliance_posture (PRD §2.10). Recomputed whenever the underlying facts
# change; a changed value is a mutation of the Student (version bump).
# ---------------------------------------------------------------------------

def compute_posture(student_id, today=None):
    if today is None:
        today = clock_date()
    for v in db.status_violations.values():
        if v["student_id"] == student_id and v["status"] in ("OPEN", "REINSTATEMENT_PENDING"):
            return "VIOLATION_OPEN"
    for a in db.address_reports.values():
        if a["student_id"] == student_id and a["status"] == "FLAGGED_LATE":
            return "AT_RISK"
    for auth in authorizations_of_student(student_id):
        if auth["auth_type"] != "OPT_POST":
            continue
        settled, _ = unemployment_counters(auth, today)
        if auth["status"] in ("APPROVED", "COMPLETED") and settled >= UNEMPLOYMENT_WARNING_DAYS:
            return "AT_RISK"
    return "CLEAR"


def recompute_posture(student_id, today=None):
    student = db.students.get(student_id)
    if student is None:
        return
    new_value = compute_posture(student_id, today)
    if new_value != student["compliance_posture"]:
        student["compliance_posture"] = new_value
        touch(student)


# ---------------------------------------------------------------------------
# extension_prorated_costs (PRD §3.8): per-line round_half_up first, then sum
# (the pinned ordering is contractual).
# ---------------------------------------------------------------------------

def prorated_lines(form, months_extended):
    lines = {}
    for key in ("tuition_cents", "living_cents", "insurance_cents", "other_cents"):
        raw = Decimal(form[key]) * months_extended / MONTHS_PER_YEAR
        lines[key] = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return lines


def extension_months(current_end_str, new_end_str):
    days_extended = (parse_date(new_end_str) - parse_date(current_end_str)).days
    return math.ceil(days_extended / DAYS_PER_MONTH)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def void_active_endorsements(form):
    for endorsement in endorsements_of_form(form["id"]):
        if endorsement["status"] == "ACTIVE":
            endorsement["status"] = "VOIDED"
            touch(endorsement)


def supersede_form(form):
    """ISSUED -> SUPERSEDED; voids each ACTIVE travel endorsement."""
    if form["status"] == "ISSUED":
        form["status"] = "SUPERSEDED"
        touch(form)
        void_active_endorsements(form)


def cancel_form(form):
    """ISSUED -> CANCELLED (record termination); voids endorsements."""
    if form["status"] == "ISSUED":
        form["status"] = "CANCELLED"
        touch(form)
        void_active_endorsements(form)


def terminate_record_cascade(record):
    """ACTIVE -> TERMINATED with the full revocation/cancellation cascade
    (PRD §3.9)."""
    student_id = record["student_id"]
    for auth in authorizations_of_student(student_id):
        if auth["status"] in ("DRAFT", "RECOMMENDED", "FILED", "APPROVED"):
            auth["status"] = "REVOKED"
            touch(auth)
            recompute_posture(student_id)
    for form in issued_forms_of_record(record["id"]):
        cancel_form(form)


def open_violation(student_id, violation_type, description):
    violation = {
        "id": new_id(),
        "student_id": student_id,
        "violation_type": violation_type,
        "description": description,
        "status": "OPEN",
    }
    stamp_new(violation)
    db.status_violations[violation["id"]] = violation
    recompute_posture(student_id)
    return violation


# ---------------------------------------------------------------------------
# Clock sweep pipeline (PRD §2.5) — six categories in fixed order.
# ---------------------------------------------------------------------------

def run_sweeps():
    today = clock_date()
    applied = []

    # (1) Transfer releases whose release_date has been reached.
    fired = False
    for tr in sorted(db.transfer_requests.values(), key=lambda e: e["_seq"]):
        if tr["status"] == "REQUESTED" and tr["direction"] == "OUT" \
                and today >= parse_date(tr["release_date"]):
            tr["status"] = "RELEASED"
            touch(tr)
            fired = True
            record = record_of_student(tr["student_id"])
            if record is not None and record["status"] == "ACTIVE":
                record["status"] = "TRANSFERRED_OUT"
                touch(record)
                for enrollment in enrollments_of_student(tr["student_id"]):
                    if enrollment["status"] == "PENDING":
                        enrollment["status"] = "NOT_ENROLLED"
                        touch(enrollment)
                        recompute_posture(tr["student_id"], today)
    if fired:
        applied.append("transfer_releases")

    # (2) Travel endorsement expiries past valid_until.
    fired = False
    for endorsement in db.travel_endorsements.values():
        if endorsement["status"] == "ACTIVE" and today > parse_date(endorsement["valid_until"]):
            endorsement["status"] = "EXPIRED"
            touch(endorsement)
            fired = True
    if fired:
        applied.append("travel_endorsement_expiries")

    # (3) Enrollment registration-deadline sweeps (still PENDING past
    # term_start_date + 30 days): flip to NOT_ENROLLED and open a
    # FAILURE_TO_ENROLL violation (which recomputes posture).
    fired = False
    for enrollment in sorted(db.term_enrollments.values(), key=lambda e: e["_seq"]):
        if enrollment["status"] == "PENDING" and today > (
            parse_date(enrollment["term_start_date"]) + timedelta(days=REGISTRATION_WINDOW_DAYS)
        ):
            enrollment["status"] = "NOT_ENROLLED"
            touch(enrollment)
            open_violation(
                enrollment["student_id"],
                "FAILURE_TO_ENROLL",
                f"Enrollment {enrollment['term_code']} was still PENDING after the "
                "registration deadline",
            )
            fired = True
    if fired:
        applied.append("enrollment_registration_deadline_sweeps")

    # (4) Record completions past program_end_date + 60-day grace, unless an
    # APPROVED OPT_POST with end_date >= clock date holds the record ACTIVE.
    fired = False
    for record in sorted(db.sevis_records.values(), key=lambda e: e["_seq"]):
        if record["status"] != "ACTIVE":
            continue
        if today <= parse_date(record["program_end_date"]) + timedelta(days=RECORD_GRACE_DAYS):
            continue
        held = False
        for auth in authorizations_of_student(record["student_id"]):
            if (
                auth["auth_type"] == "OPT_POST"
                and auth["status"] == "APPROVED"
                and parse_date(auth["end_date"]) >= today
            ):
                held = True
                break
        if held:
            continue
        record["status"] = "COMPLETED"
        touch(record)
        for auth in authorizations_of_student(record["student_id"]):
            if auth["status"] == "APPROVED":
                auth["status"] = "COMPLETED"
                touch(auth)
        recompute_posture(record["student_id"], today)
        fired = True
    if fired:
        applied.append("record_completions")

    # (4b) PRD §3.5: an APPROVED authorization whose end_date has passed flips
    # to COMPLETED under the clock sweep.
    fired = False
    for auth in sorted(db.employment_authorizations.values(), key=lambda e: e["_seq"]):
        if auth["status"] == "APPROVED" and today > parse_date(auth["end_date"]):
            auth["status"] = "COMPLETED"
            touch(auth)
            fired = True
    if fired:
        applied.append("employment_authorization_completions")

    # (5) OPT_POST unemployment-limit violation check: settled > 90 opens an
    # UNEMPLOYMENT_LIMIT_EXCEEDED violation (one open at a time per student).
    fired = False
    for auth in sorted(db.employment_authorizations.values(), key=lambda e: e["_seq"]):
        if auth["auth_type"] != "OPT_POST" or auth["status"] != "APPROVED":
            continue
        settled, _ = unemployment_counters(auth, today)
        if settled > UNEMPLOYMENT_LIMIT_DAYS:
            already_open = any(
                v["student_id"] == auth["student_id"]
                and v["violation_type"] == "UNEMPLOYMENT_LIMIT_EXCEEDED"
                and v["status"] in ("OPEN", "REINSTATEMENT_PENDING")
                for v in db.status_violations.values()
            )
            if not already_open:
                open_violation(
                    auth["student_id"],
                    "UNEMPLOYMENT_LIMIT_EXCEEDED",
                    "OPT_POST unemployment day limit exceeded",
                )
                fired = True
    if fired:
        applied.append("opt_post_unemployment_limit_checks")

    # (6) Enrollment term-end completions (REGISTERED past term_end_date).
    fired = False
    for enrollment in db.term_enrollments.values():
        if enrollment["status"] == "REGISTERED" and today > parse_date(enrollment["term_end_date"]):
            enrollment["status"] = "COMPLETED"
            touch(enrollment)
            fired = True
    if fired:
        applied.append("enrollment_term_end_completions")

    # Counter drift under the new clock can move posture across the 75-day
    # warning line without any other write (PRD §2.10 / §3.5).
    for student in db.students.values():
        recompute_posture(student["id"], today)

    return applied
