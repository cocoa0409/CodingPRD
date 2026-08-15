"""Shared entity helpers, serialization, and derived/computed logic."""

from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from db import store, fmt_ts, new_id, parse_iso
from errors import not_found, invalid_request


# ---------------------------------------------------------------------------
# date/time helpers
# ---------------------------------------------------------------------------

def parse_date(s, field="date"):
    if not isinstance(s, str):
        raise invalid_request(f"{field} must be a string date")
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise invalid_request(f"{field} must be ISO date YYYY-MM-DD")


def parse_time(s, field="time"):
    """Parse HH:MM 24h -> minutes since midnight."""
    if not isinstance(s, str):
        raise invalid_request(f"{field} must be HH:MM string")
    parts = s.split(":")
    if len(parts) != 2:
        raise invalid_request(f"{field} must be HH:MM")
    try:
        h = int(parts[0])
        m = int(parts[1])
    except ValueError:
        raise invalid_request(f"{field} must be HH:MM")
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise invalid_request(f"{field} out of range")
    return h * 60 + m


def round_half_up_cents(value):
    """value is Decimal -> integer cents with ROUND_HALF_UP."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round Decimal to 2 decimal places, half up. Returns float for JSON."""
    q = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


# ---------------------------------------------------------------------------
# generic record factory / touch
# ---------------------------------------------------------------------------

def base_record():
    ts = store.now_str()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(rec):
    rec["updated_at"] = store.now_str()
    rec["version"] = rec.get("version", 1) + 1


def touch_no_version(rec):
    rec["updated_at"] = store.now_str()


def public(rec):
    """Strip private keys (underscore-prefixed)."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# getters with 404
# ---------------------------------------------------------------------------

def get_year(year_id):
    rec = store.school_years.get(year_id)
    if rec is None:
        raise not_found("SchoolYear not found")
    return rec


def get_security_plan(plan_id):
    rec = store.security_plans.get(plan_id)
    if rec is None:
        raise not_found("SecurityPlan not found")
    return rec


def get_family(family_id):
    rec = store.families.get(family_id)
    if rec is None:
        raise not_found("Family not found")
    return rec


def get_student(student_id):
    rec = store.students.get(student_id)
    if rec is None:
        raise not_found("Student not found")
    return rec


def get_teacher(teacher_id):
    rec = store.teachers.get(teacher_id)
    if rec is None:
        raise not_found("Teacher not found")
    return rec


def get_section(section_id):
    rec = store.sections.get(section_id)
    if rec is None:
        raise not_found("Section not found")
    return rec


def get_enrollment(enrollment_id):
    rec = store.enrollments.get(enrollment_id)
    if rec is None:
        raise not_found("Enrollment not found")
    return rec


def get_invoice(invoice_id):
    rec = store.invoices.get(invoice_id)
    if rec is None:
        raise not_found("TuitionInvoice not found")
    return rec


def get_payment(payment_id):
    rec = store.payments.get(payment_id)
    if rec is None:
        raise not_found("Payment not found")
    return rec


def get_application(app_id):
    rec = store.applications.get(app_id)
    if rec is None:
        raise not_found("AssistanceApplication not found")
    return rec


def get_session(session_id):
    rec = store.sessions.get(session_id)
    if rec is None:
        raise not_found("Session not found")
    return rec


def get_milestone(milestone_id):
    rec = store.milestones.get(milestone_id)
    if rec is None:
        raise not_found("Milestone not found")
    return rec


def get_commitment(commitment_id):
    rec = store.commitments.get(commitment_id)
    if rec is None:
        raise not_found("VolunteerCommitment not found")
    return rec


# ---------------------------------------------------------------------------
# derived fields
# ---------------------------------------------------------------------------

def staffing_status(section):
    tid = section.get("teacher_id")
    if not tid:
        return "UNSTAFFED"
    teacher = store.teachers.get(tid)
    if teacher and teacher.get("status") == "HIRED":
        return "STAFFED"
    return "UNSTAFFED"


def serialize_section(section):
    out = public(section)
    out["staffing_status"] = staffing_status(section)
    return out


def recompute_family_outstanding(family):
    total = 0
    for inv in store.invoices.values():
        if inv["family_id"] == family["id"] and inv["status"] in ("ISSUED", "PARTIALLY_PAID"):
            total += inv["balance_cents"]
    family["outstanding_balance_cents"] = total


def family_year_enrollments(family_id, year_id):
    """Enrollments of family in year eligible for sibling ranking (WITHDRAWN excluded)."""
    out = []
    for e in store.enrollments.values():
        if e["family_id"] == family_id and e["school_year_id"] == year_id and e["status"] in (
            "REGISTERED", "ACTIVE", "COMPLETED"
        ):
            out.append(e)
    # sort by created_at ASC, tie broken by server request-arrival order (_seq)
    out.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return out


def compute_net_tuition(year, family, enrollment):
    """The enrollment_net_tuition formula. Returns integer cents."""
    base = (
        year["member_tuition_cents"]
        if family["membership_status"] == "MEMBER"
        else year["non_member_tuition_cents"]
    )
    rank_set = family_year_enrollments(family["id"], year["id"])
    # find rank
    rank = 0
    for i, e in enumerate(rank_set):
        if e["id"] == enrollment["id"]:
            rank = i
            break
    pcts = year["sibling_discount_pcts"] or [0]
    idx = min(rank, len(pcts) - 1)
    disc = Decimal(str(pcts[idx]))
    after_sibling = round_half_up_cents(Decimal(base) * (Decimal(1) - disc))
    early_deadline = parse_iso(year["early_bird_deadline"])
    created = parse_iso(enrollment["created_at"])
    if created < early_deadline:
        line = round_half_up_cents(
            Decimal(after_sibling) * (Decimal(1) - Decimal(str(year["early_bird_pct"])))
        )
    else:
        line = after_sibling
    return line, rank


# ---------------------------------------------------------------------------
# attendance / milestone recompute
# ---------------------------------------------------------------------------

ATT_WEIGHTS = {"PRESENT": Decimal("1.0"), "EXCUSED": Decimal("0.5"), "ABSENT": Decimal("0.0")}


def _student_enrollment_for_section(student_id, section_id):
    """Return the student's enrollment on this section (any non-WITHDRAWN state counts as having been enrolled);
    we need REGISTERED/ACTIVE/COMPLETED/WITHDRAWN history for eligibility of sessions held while enrolled."""
    for e in store.enrollments.values():
        if e["student_id"] == student_id and e["section_id"] == section_id:
            return e
    return None


def attendance_pcts(student_id, section_id):
    """Return (current_pct, projected_pct) as 2-dp floats.

    eligible_sessions(s) = Sessions of the student's enrolled section with status HELD AND
    non-empty attendance array, while the student's enrollment status was IN {REGISTERED, ACTIVE}.
    """
    enrollment = _student_enrollment_for_section(student_id, section_id)
    if enrollment is None:
        return 0.0, 0.0

    sessions = [s for s in store.sessions.values() if s["section_id"] == section_id]
    sessions.sort(key=lambda s: (s["session_date"], s["_seq"]))

    eligible = []
    scheduled_count = 0
    for s in sessions:
        if s["status"] == "HELD" and len(s.get("attendance", [])) > 0:
            eligible.append(s)
        if s["status"] == "SCHEDULED":
            scheduled_count += 1

    denominator = len(eligible)
    if denominator == 0:
        current = 0.0
    else:
        numerator = Decimal(0)
        for s in eligible:
            mark = None
            for entry in s["attendance"]:
                if entry["student_id"] == student_id:
                    mark = entry["status"]
                    break
            if mark is None:
                numerator += Decimal("0.0")
            else:
                numerator += ATT_WEIGHTS.get(mark, Decimal("0.0"))
        current = round_half_up_2dp((Decimal(100) * numerator) / Decimal(denominator))

    proj_denom = denominator + scheduled_count
    if proj_denom == 0:
        projected = 0.0
    else:
        numerator2 = Decimal(0)
        for s in eligible:
            mark = None
            for entry in s["attendance"]:
                if entry["student_id"] == student_id:
                    mark = entry["status"]
                    break
            if mark is None:
                numerator2 += Decimal("0.0")
            else:
                numerator2 += ATT_WEIGHTS.get(mark, Decimal("0.0"))
        numerator2 += Decimal(scheduled_count)
        projected = round_half_up_2dp((Decimal(100) * numerator2) / Decimal(proj_denom))

    return current, projected


def reevaluate_milestone(milestone):
    year = store.school_years.get(milestone["school_year_id"])
    if year is None:
        return
    # find the student's section in this year (their enrollment's section)
    enrollment = None
    for e in store.enrollments.values():
        if (
            e["student_id"] == milestone["student_id"]
            and e["school_year_id"] == milestone["school_year_id"]
            and e["status"] in ("REGISTERED", "ACTIVE", "COMPLETED", "WITHDRAWN")
        ):
            enrollment = e
            break
    if enrollment is None:
        return
    current, projected = attendance_pcts(milestone["student_id"], enrollment["section_id"])
    milestone["current_attendance_pct"] = current
    milestone["projected_attendance_pct"] = projected
    threshold = float(year["attendance_threshold_pct"])
    if milestone["status"] in ("TRACKING", "ELIGIBLE"):
        if current >= threshold:
            milestone["status"] = "ELIGIBLE"
        else:
            milestone["status"] = "TRACKING"
    touch_no_version(milestone)


def reevaluate_milestones_for_section(section_id):
    """After session hold/cancel/attendance — recompute milestones of all students enrolled in the section."""
    affected = set()
    for e in store.enrollments.values():
        if e["section_id"] == section_id and e["status"] in ("REGISTERED", "ACTIVE"):
            affected.add(e["student_id"])
    for m in store.milestones.values():
        if m["student_id"] in affected:
            reevaluate_milestone(m)


# ---------------------------------------------------------------------------
# commitment helpers
# ---------------------------------------------------------------------------

def recompute_commitment(commitment):
    total = Decimal(0)
    for entry in commitment["entries"]:
        if entry["status"] == "ACTIVE":
            total += Decimal(str(entry["hours"]))
    commitment["logged_hours"] = float(total) if total % 1 else int(total)
    return commitment["logged_hours"]


def regress_commitment_if_needed(commitment):
    """After an entry void: FULFILLED -> OPEN if below required, revert SCHEDULED milestones of family+year."""
    logged = recompute_commitment(commitment)
    if commitment["status"] == "FULFILLED" and logged < commitment["required_hours"]:
        commitment["status"] = "OPEN"
        # revert SCHEDULED milestones of this family in this year to ELIGIBLE
        for m in store.milestones.values():
            if (
                m["family_id"] == commitment["family_id"]
                and m["school_year_id"] == commitment["school_year_id"]
                and m["status"] == "SCHEDULED"
            ):
                m["status"] = "ELIGIBLE"
                touch_no_version(m)
    touch_no_version(commitment)
