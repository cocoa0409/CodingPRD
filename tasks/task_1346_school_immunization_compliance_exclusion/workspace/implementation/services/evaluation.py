"""Requirement evaluation, next-dose-due computation, and student status transitions.

Implements PRD §2.4 (academic year), §2.9 (two lenses), §3.1, §3.5.
"""

from datetime import timedelta

import db
from db import clock, parse_iso, format_iso, touch


VACCINE_CODES = ["DTAP", "IPV", "MMR", "HEPB", "VAR", "HIB", "PCV", "HEPA"]
GRADES = ["PK", "K", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8",
          "G9", "G10", "G11", "G12"]

LOCAL_SOURCES = {"MANUAL", "CLINIC"}
RECONCILED_SOURCES = {"MANUAL", "CLINIC", "REGISTRY_IMPORT"}


# ---------------------------------------------------------------------------
# Academic year per PRD §2.4
# ---------------------------------------------------------------------------

def academic_year_label(dt):
    """Aug 1 .. Jul 31 -> 'YYYY-(YYYY+1)'."""
    if dt.month >= 8:
        start = dt.year
    else:
        start = dt.year - 1
    return f"{start}-{start + 1}"


def add_months(dt, months):
    """Calendar-month addition."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp day to end of target month
    if month == 12:
        next_first = dt.replace(year=year + 1, month=1, day=1)
    else:
        next_first = dt.replace(year=year, month=month + 1, day=1)
    last_day = (next_first - timedelta(days=1)).day
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


# ---------------------------------------------------------------------------
# Requirement applicability & evaluation
# ---------------------------------------------------------------------------

def applicable_requirements(student, at_dt=None):
    """VaccineRequirements applying to this student per PRD §3.2.

    A requirement applies when the student's grade is among applies_to_grades
    and its school_year equals the academic-year label of the current logical
    clock.
    """
    if at_dt is None:
        at_dt = clock.now()
    year_label = academic_year_label(at_dt)
    out = []
    for req in db.vaccine_requirements.values():
        if req["school_year"] != year_label:
            continue
        if student["grade"] not in req["applies_to_grades"]:
            continue
        out.append(req)
    return out


def _verified_local_records(student_id, vaccine_code):
    out = []
    for rec in db.immunization_records.values():
        if rec["student_id"] != student_id:
            continue
        if rec["vaccine_code"] != vaccine_code:
            continue
        if rec["status"] != "VERIFIED":
            continue
        if rec["source"] not in LOCAL_SOURCES:
            continue
        out.append(rec)
    return out


def _verified_reconciled_records(student_id, vaccine_code):
    out = []
    for rec in db.immunization_records.values():
        if rec["student_id"] != student_id:
            continue
        if rec["vaccine_code"] != vaccine_code:
            continue
        if rec["status"] != "VERIFIED":
            continue
        if rec["source"] not in RECONCILED_SOURCES:
            continue
        out.append(rec)
    return out


def _has_approved_exemption(student_id, vaccine_code):
    for ex in db.exemption_requests.values():
        if ex["student_id"] == student_id and ex["vaccine_code"] == vaccine_code \
                and ex["status"] == "APPROVED":
            return True
    return False


def _has_suspended_exemption(student_id, vaccine_code):
    for ex in db.exemption_requests.values():
        if ex["student_id"] == student_id and ex["vaccine_code"] == vaccine_code \
                and ex["status"] == "SUSPENDED_OUTBREAK":
            return True
    return False


def evaluate_requirement(student, req, variant):
    """Return True if the requirement is satisfied under the given variant."""
    if variant == "LOCAL_RECORDS":
        records = _verified_local_records(student["id"], req["vaccine_code"])
    else:
        records = _verified_reconciled_records(student["id"], req["vaccine_code"])
    if len(records) >= req["doses_required"]:
        return True
    if _has_approved_exemption(student["id"], req["vaccine_code"]):
        return True
    return False


def deficiency_codes(student):
    """Vaccine codes NOT_SATISFIED under LOCAL_RECORDS."""
    out = []
    for req in applicable_requirements(student):
        if not evaluate_requirement(student, req, "LOCAL_RECORDS"):
            out.append(req["vaccine_code"])
    return out


# ---------------------------------------------------------------------------
# Next-dose due date per calculation `next_dose_due_date`
# ---------------------------------------------------------------------------

def next_dose_due_date(student, req):
    """Per scaffold calculation next_dose_due_date."""
    if _has_approved_exemption(student["id"], req["vaccine_code"]):
        return None
    dob = parse_iso(student["date_of_birth"])
    enrollment = parse_iso(student["enrollment_date"])
    base = add_months(dob, req["min_age_months"])
    local_records = _verified_local_records(student["id"], req["vaccine_code"])
    if not local_records:
        due = max(base, enrollment)
    else:
        last_dose = max(parse_iso(r["administered_date"]) for r in local_records)
        due = max(base, last_dose + timedelta(days=req["min_interval_days"]))
    if _has_suspended_exemption(student["id"], req["vaccine_code"]):
        now = clock.now()
        if now < due:
            due = now
    return due


# ---------------------------------------------------------------------------
# Student status transition engine (drives state machine §1.2 Student)
# ---------------------------------------------------------------------------

def reevaluate_student(student):
    """Recompute deficiency_vaccine_codes and apply the Student state machine.

    This runs the LOCAL_RECORDS-driven transitions:
      - -> ENROLLED_COMPLIANT when all-satisfied (from ENROLLED_PROVISIONAL,
        NON_COMPLIANT, EXCLUDED via readmission)
      - ENROLLED_COMPLIANT -> ENROLLED_PROVISIONAL / NON_COMPLIANT when a void
        breaks satisfaction (handled by callers; this function only moves
        students toward compliance)

    Returns True if the student's status changed.
    """
    codes = deficiency_codes(student)
    student["deficiency_vaccine_codes"] = codes
    changed = False
    if not codes:
        if student["status"] in ("ENROLLED_PROVISIONAL", "NON_COMPLIANT", "EXCLUDED"):
            # cure notices
            if student["status"] in ("NON_COMPLIANT", "EXCLUDED"):
                _cure_notices_for_student(student)
            student["status"] = "ENROLLED_COMPLIANT"
            student["deficiency_vaccine_codes"] = []
            changed = True
    touch(student)
    return changed


def _cure_notices_for_student(student):
    """Cure ISSUED and EXCLUSION_EFFECTIVE notices for the student."""
    now_iso = format_iso(clock.now())
    for notice in db.compliance_notices.values():
        if notice["student_id"] != student["id"]:
            continue
        if notice["status"] in ("ISSUED", "EXCLUSION_EFFECTIVE"):
            notice["status"] = "CURED"
            notice["resolved_at"] = now_iso
            touch(notice)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def student_view(s):
    return {
        "id": s["id"],
        "legal_name": s["legal_name"],
        "date_of_birth": s["date_of_birth"],
        "grade": s["grade"],
        "school_code": s["school_code"],
        "enrollment_date": s["enrollment_date"],
        "status": s["status"],
        "provisional_deadline": s["provisional_deadline"],
        "deficiency_vaccine_codes": list(s["deficiency_vaccine_codes"]),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def requirement_view(r):
    return {
        "id": r["id"],
        "vaccine_code": r["vaccine_code"],
        "applies_to_grades": list(r["applies_to_grades"]),
        "doses_required": r["doses_required"],
        "min_interval_days": r["min_interval_days"],
        "min_age_months": r["min_age_months"],
        "school_year": r["school_year"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def record_view(r):
    return {
        "id": r["id"],
        "student_id": r["student_id"],
        "vaccine_code": r["vaccine_code"],
        "dose_number": r["dose_number"],
        "administered_date": r["administered_date"],
        "source": r["source"],
        "clinic_appointment_id": r.get("clinic_appointment_id"),
        "status": r["status"],
        "verified_by_user_id": r.get("verified_by_user_id"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def exemption_view(e):
    return {
        "id": e["id"],
        "student_id": e["student_id"],
        "vaccine_code": e["vaccine_code"],
        "exemption_type": e["exemption_type"],
        "document_ref": e["document_ref"],
        "status": e["status"],
        "submitted_by_user_id": e["submitted_by_user_id"],
        "reviewed_by_user_id": e.get("reviewed_by_user_id"),
        "denial_reason": e.get("denial_reason"),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def notice_view(n):
    return {
        "id": n["id"],
        "student_id": n["student_id"],
        "notice_type": n["notice_type"],
        "status": n["status"],
        "issue_date": n["issue_date"],
        "exclusion_date": n["exclusion_date"],
        "resolved_at": n.get("resolved_at"),
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
    }


def outbreak_view(o):
    return {
        "id": o["id"],
        "school_code": o["school_code"],
        "vaccine_code": o["vaccine_code"],
        "status": o["status"],
        "declared_at": o["declared_at"],
        "lifted_at": o.get("lifted_at"),
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def session_view(s):
    return {
        "id": s["id"],
        "school_code": s["school_code"],
        "session_date": s["session_date"],
        "duration_minutes": s["duration_minutes"],
        "capacity": s["capacity"],
        "booked_count": s["booked_count"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def appointment_view(a):
    return {
        "id": a["id"],
        "clinic_session_id": a["clinic_session_id"],
        "student_id": a["student_id"],
        "vaccine_code": a["vaccine_code"],
        "start_time": a["start_time"],
        "end_time": a["end_time"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def sync_run_view(r):
    return {
        "id": r["id"],
        "school_code": r["school_code"],
        "status": r["status"],
        "registry_doses_seen": r["registry_doses_seen"],
        "imported_count": r["imported_count"],
        "matched_count": r["matched_count"],
        "discrepancy_count": r["discrepancy_count"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def snapshot_view(s):
    return {
        "id": s["id"],
        "school_year": s["school_year"],
        "school_code": s["school_code"],
        "grade": s["grade"],
        "census_date": s["census_date"],
        "rate_variant": s["rate_variant"],
        "enrolled_count": s["enrolled_count"],
        "compliant_count": s["compliant_count"],
        "exempt_count": s["exempt_count"],
        "compliance_rate": s["compliance_rate"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }
