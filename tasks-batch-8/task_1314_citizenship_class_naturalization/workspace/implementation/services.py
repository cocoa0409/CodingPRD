"""Business logic: calculations, sweeps, seat ledger, serializers."""
from datetime import timedelta
from fractions import Fraction
from math import floor

from db import (db, Rec, fmt_dt, now_dt, bump, prog_param, add_months,
                stamp_new, stamp_new_appendonly)
from errors import conflict

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _common(rec):
    return {
        "id": rec.id,
        "created_at": fmt_dt(rec.created_at),
        "updated_at": fmt_dt(rec.updated_at),
        "version": rec.version,
    }


def ser_program(p):
    out = _common(p)
    out.update({
        "name": p.name,
        "n400_fee_cents": p.n400_fee_cents,
        "biometric_fee_cents": p.biometric_fee_cents,
        "translation_stipend_cents": p.translation_stipend_cents,
        "poverty_base_cents": p.poverty_base_cents,
        "poverty_per_additional_cents": p.poverty_per_additional_cents,
        "full_waiver_threshold_pct": p.full_waiver_threshold_pct,
        "partial_waiver_threshold_pct": p.partial_waiver_threshold_pct,
        "attendance_complete_bp": p.attendance_complete_bp,
        "attendance_midterm_floor_bp": p.attendance_midterm_floor_bp,
        "readiness_certify_threshold": p.readiness_certify_threshold,
        "rfe_deadline_days": p.rfe_deadline_days,
        "accreditation_valid_months": p.accreditation_valid_months,
        "general_training_hours": p.general_training_hours,
        "legal_supervised_hours": p.legal_supervised_hours,
        "renewal_training_hours": p.renewal_training_hours,
        "promotion_offer_hours": p.promotion_offer_hours,
        "mock_buffer_minutes": p.mock_buffer_minutes,
        "mock_max_attempts": p.mock_max_attempts,
    })
    return out


def ser_applicant(a):
    out = _common(a)
    out.update({
        "full_name": a.full_name,
        "email": a.email,
        "date_of_birth": a.date_of_birth,
        "preferred_language": a.preferred_language,
        "stage": a.stage,
        "current_screening_id": a.current_screening_id,
        "voter_registration_referred": a.voter_registration_referred,
    })
    return out


def ser_screening(s):
    out = _common(s)
    out.update({
        "applicant_id": s.applicant_id,
        "marital_to_citizen": s.marital_to_citizen,
        "lpr_months": s.lpr_months,
        "continuous_residence_months": s.continuous_residence_months,
        "physical_presence_days": s.physical_presence_days,
        "age_years": s.age_years,
        "english_level": s.english_level,
        "civics_practice_pct": s.civics_practice_pct,
        "has_legal_flag": s.has_legal_flag,
        "outcome": s.outcome,
        "status": s.status,
        "expires_at": fmt_dt(s.expires_at),
    })
    return out


def ser_section(s):
    out = _common(s)
    out.update({
        "title": s.title,
        "weekday": s.weekday,
        "start_minute": s.start_minute,
        "end_minute": s.end_minute,
        "room_id": s.room_id,
        "instructor_volunteer_id": s.instructor_volunteer_id,
        "capacity": s.capacity,
        "total_sessions": s.total_sessions,
        "enrolled_count": s.enrolled_count,
        "pending_promotion_count": s.pending_promotion_count,
        "waitlisted_count": s.waitlisted_count,
        "seats_open": s.capacity - s.enrolled_count - s.pending_promotion_count,
    })
    return out


def ser_enrollment(e):
    out = _common(e)
    out.update({
        "applicant_id": e.applicant_id,
        "class_section_id": e.class_section_id,
        "status": e.status,
        "attendance_bp": e.attendance_bp,
        "records_count": e.records_count,
        "offer_expires_at": fmt_dt(e.offer_expires_at) if e.offer_expires_at else None,
    })
    return out


def ser_attendance(r):
    return {
        "id": r.id,
        "created_at": fmt_dt(r.created_at),
        "enrollment_id": r.enrollment_id,
        "session_index": r.session_index,
        "outcome": r.outcome,
    }


def training_hours_24mo(volunteer):
    """Sum of hours earned at or after clock - 730 days (inclusive boundary)."""
    cutoff = now_dt() - timedelta(days=730)
    total = 0
    for c in db.training.values():
        if c.volunteer_id == volunteer.id and c.earned_at_dt >= cutoff:
            total += c.hours
    return total


def ser_volunteer(v):
    out = _common(v)
    out.update({
        "full_name": v.full_name,
        "email": v.email,
        "background_check_cleared": v.background_check_cleared,
        "bar_number": v.bar_number,
        "accreditation_level": v.accreditation_level,
        "lapsed_from_level": v.lapsed_from_level,
        "accredited_at": fmt_dt(v.accredited_at) if v.accredited_at else None,
        "training_hours_24mo": training_hours_24mo(v),
        "supervised_hours": v.supervised_hours,
    })
    return out


def ser_training_credit(c):
    return {
        "id": c.id,
        "created_at": fmt_dt(c.created_at),
        "volunteer_id": c.volunteer_id,
        "topic": c.topic,
        "hours": c.hours,
        "earned_at": c.earned_at_raw,
    }


def ser_workshop(w):
    out = _common(w)
    out.update({
        "title": w.title,
        "supervising_volunteer_id": w.supervising_volunteer_id,
        "assisting_volunteer_id": w.assisting_volunteer_id,
        "scheduled_start": w.scheduled_start_raw,
        "duration_hours": w.duration_hours,
        "capacity": w.capacity,
        "reserved_count": w.reserved_count,
        "status": w.status,
    })
    return out


def ser_seat(s):
    out = _common(s)
    out.update({
        "workshop_id": s.workshop_id,
        "applicant_id": s.applicant_id,
        "status": s.status,
    })
    return out


def ser_packet(p):
    out = _common(p)
    out.update({
        "applicant_id": p.applicant_id,
        "workshop_seat_id": p.workshop_seat_id,
        "prepared_by_volunteer_id": p.prepared_by_volunteer_id,
        "fee_waiver_request_id": p.fee_waiver_request_id,
        "status": p.status,
        "certified_by_volunteer_id": p.certified_by_volunteer_id,
        "filing_fee_cents": p.filing_fee_cents,
    })
    return out


def ser_fee_waiver(r):
    out = _common(r)
    out.update({
        "applicant_id": r.applicant_id,
        "household_size": r.household_size,
        "self_reported_income_cents": r.self_reported_income_cents,
        "self_reported_benefit": r.self_reported_benefit,
        "provisional_tier": r.provisional_tier,
        "attached_document_count": r.attached_document_count,
        "required_document_count": r.required_document_count,
        "status": r.status,
        "documented_income_cents": r.documented_income_cents,
        "documented_benefit": r.documented_benefit,
        "final_tier": r.final_tier,
        "decided_by": r.decided_by,
    })
    return out


def ser_case(c):
    out = _common(c)
    out.update({
        "applicant_id": c.applicant_id,
        "packet_id": c.packet_id,
        "receipt_number": c.receipt_number,
        "stage": c.stage,
        "rfe_status": c.rfe_status,
        "rfe_issued_at": fmt_dt(c.rfe_issued_at) if c.rfe_issued_at else None,
        "rfe_deadline": fmt_dt(c.rfe_deadline) if c.rfe_deadline else None,
        "oath_ceremony_id": c.oath_ceremony_id,
    })
    return out


def ser_mock(m):
    out = _common(m)
    out.update({
        "applicant_id": m.applicant_id,
        "volunteer_id": m.volunteer_id,
        "scheduled_start": m.scheduled_start_raw,
        "duration_minutes": m.duration_minutes,
        "status": m.status,
        "english_pct": m.english_pct,
        "civics_pct": m.civics_pct,
        "n400_pct": m.n400_pct,
        "overall_score": m.overall_score,
        "outcome": m.outcome,
    })
    return out


def ser_ceremony(c):
    out = _common(c)
    out.update({
        "ceremony_date": c.ceremony_date_raw,
        "venue": c.venue,
        "capacity": c.capacity,
        "assigned_count": c.assigned_count,
        "status": c.status,
    })
    return out


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def screening_outcome(marital_to_citizen, lpr_months, continuous_residence_months,
                      physical_presence_days, age_years, english_level,
                      civics_practice_pct, has_legal_flag):
    res_req = 36 if marital_to_citizen else 60
    pres_req = 548 if marital_to_citizen else 913
    if continuous_residence_months < res_req:
        return "NOT_ELIGIBLE"
    if physical_presence_days < pres_req:
        return "NOT_ELIGIBLE"
    if has_legal_flag:
        return "NEEDS_REVIEW"
    if english_level >= 1:
        return "ELIGIBLE"
    if age_years >= 55 and lpr_months >= 180:
        return "ELIGIBLE_WITH_EXEMPTION"
    return "NOT_ELIGIBLE"


def fee_waiver_tier(household_size, income_cents, benefit):
    guideline = prog_param("poverty_base_cents") + \
        prog_param("poverty_per_additional_cents") * (household_size - 1)
    if benefit:
        return "FULL"
    if income_cents * 100 <= guideline * prog_param("full_waiver_threshold_pct"):
        return "FULL"
    if income_cents * 100 <= guideline * prog_param("partial_waiver_threshold_pct"):
        return "PARTIAL"
    return "DENIED"


def required_document_count(household_size, benefit):
    return 2 if benefit else household_size + 1


def filing_fee_cents(final_tier):
    """Pinned order: resolve tier, discount per line (round half up), then sum."""
    lines = [prog_param("n400_fee_cents"), prog_param("biometric_fee_cents"),
             prog_param("translation_stipend_cents")]
    if final_tier == "FULL":
        return 0
    if final_tier == "PARTIAL":
        return sum((line * 50 + 50) // 100 for line in lines)
    return sum(lines)


def _round_half_up(frac):
    return floor(frac + Fraction(1, 2))


def _active_screening(applicant):
    sid = applicant.current_screening_id
    if not sid:
        return None
    s = db.screenings.get(sid)
    if s is None or s.status != "ACTIVE":
        return None
    return s


def readiness(applicant, variant):
    """Returns dict with score and component points."""
    s = _active_screening(applicant)
    if s is None:
        return {"variant": variant, "score": 0, "residence_points": 0,
                "presence_points": 0, "english_points": 0, "civics_points": 0,
                "legal_points": 0}
    res_req = 36 if s.marital_to_citizen else 60
    pres_req = 548 if s.marital_to_citizen else 913
    res_pts = 25 if s.continuous_residence_months >= res_req else 0
    pres_pts = 25 if s.physical_presence_days >= pres_req else 0

    completed_scores = [m.overall_score for m in db.mocks.values()
                        if m.applicant_id == applicant.id
                        and m.status == "COMPLETED"
                        and m.overall_score is not None]
    civics_best = max([s.civics_practice_pct] + completed_scores)
    eng_level = s.english_level

    if variant == "projected":
        has_enrolled = any(e.applicant_id == applicant.id and e.status == "ENROLLED"
                           for e in db.enrollments.values())
        if has_enrolled:
            eng_level = min(4, eng_level + 1)
        has_scheduled_mock = any(m.applicant_id == applicant.id and m.status == "SCHEDULED"
                                 for m in db.mocks.values())
        if has_scheduled_mock:
            civics_best = max(civics_best, 70)

    eng_pts = Fraction(20 * eng_level, 4)
    civ_pts = Fraction(20 * civics_best, 100)
    legal_pts = 0 if s.has_legal_flag else 10
    total = res_pts + pres_pts + eng_pts + civ_pts + legal_pts
    return {
        "variant": variant,
        "score": _round_half_up(total),
        "residence_points": res_pts,
        "presence_points": pres_pts,
        "english_points": _round_half_up(eng_pts),
        "civics_points": _round_half_up(civ_pts),
        "legal_points": legal_pts,
    }


def attained_readiness_score(applicant):
    return readiness(applicant, "attained")["score"]


# ---------------------------------------------------------------------------
# Guards shared by several endpoints
# ---------------------------------------------------------------------------

def check_accreditation(volunteer, required):
    """required: 'GENERAL_OR_LEGAL' or 'LEGAL'."""
    lvl = volunteer.accreditation_level
    if required == "LEGAL":
        if lvl == "LEGAL":
            return
        if lvl == "LAPSED":
            raise conflict("ERR_ACCREDITATION_LAPSED",
                           "Required accreditation has lapsed")
        raise conflict("ERR_ACCREDITATION_INSUFFICIENT",
                       "Required accreditation level not held")
    if lvl in ("GENERAL", "LEGAL"):
        return
    if lvl == "LAPSED":
        raise conflict("ERR_ACCREDITATION_LAPSED",
                       "Required accreditation has lapsed")
    raise conflict("ERR_ACCREDITATION_INSUFFICIENT",
                   "Required accreditation level not held")


def eligible_active_screening(applicant):
    """Returns the applicant's ACTIVE eligible screening; raises otherwise.

    Eligibility (outcome) is evaluated before the temporal expiry guard.
    """
    s = _active_screening(applicant)
    if s is None or s.outcome not in ("ELIGIBLE", "ELIGIBLE_WITH_EXEMPTION"):
        raise conflict("ERR_SCREENING_NOT_ELIGIBLE",
                       "No ACTIVE screening with an eligible outcome")
    if not (s.expires_at > now_dt()):
        raise conflict("ERR_SCREENING_EXPIRED", "ACTIVE screening has expired")
    return s


# ---------------------------------------------------------------------------
# Seat ledger / promotion
# ---------------------------------------------------------------------------

def run_promotion_selector(section):
    """Promote WAITLISTED enrollments while seats remain open.

    Selector: earliest created_at (insertion order breaks the impossible tie).
    """
    while True:
        seats_open = section.capacity - section.enrolled_count - section.pending_promotion_count
        if seats_open < 1:
            return
        waiting = [e for e in db.enrollments.values()
                   if e.class_section_id == section.id and e.status == "WAITLISTED"]
        if not waiting:
            return
        waiting.sort(key=lambda e: (e.created_at, e._seq))
        target = waiting[0]
        target.status = "PENDING_PROMOTION"
        target.offer_expires_at = now_dt() + timedelta(
            hours=prog_param("promotion_offer_hours"))
        bump(target)
        section.waitlisted_count -= 1
        section.pending_promotion_count += 1
        bump(section)


def maybe_advance_to_pipeline(applicant):
    if applicant.stage == "SCREENED":
        applicant.stage = "IN_PIPELINE"
        bump(applicant)


def recompute_attendance(enrollment):
    recs = [r for r in db.attendance.values() if r.enrollment_id == enrollment.id]
    enrollment.records_count = len(recs)
    if not recs:
        enrollment.attendance_bp = 0
    else:
        attended = sum(1 for r in recs if r.outcome in ("PRESENT", "ABSENT_EXCUSED"))
        enrollment.attendance_bp = (attended * 10000) // len(recs)


def midterm_revoke_check(enrollment, section):
    """Fires exactly once, when records_count first reaches the midterm point."""
    if enrollment.status != "ENROLLED":
        return
    midterm_point = (section.total_sessions + 1) // 2
    if enrollment.records_count == midterm_point and \
            enrollment.attendance_bp < prog_param("attendance_midterm_floor_bp"):
        enrollment.status = "REVOKED"
        bump(enrollment)
        section.enrolled_count -= 1
        bump(section)
        run_promotion_selector(section)


# ---------------------------------------------------------------------------
# Clock sweeps
# ---------------------------------------------------------------------------

def run_sweeps(new_now):
    # 1. Accreditation lapse (anniversary strictly earlier than the new reading)
    months = prog_param("accreditation_valid_months")
    for v in db.volunteers.values():
        if v.accreditation_level in ("GENERAL", "LEGAL") and v.accredited_at is not None:
            if add_months(v.accredited_at, months) < new_now:
                v.lapsed_from_level = v.accreditation_level
                v.accreditation_level = "LAPSED"
                bump(v)
    # 2. RFE deadline sweep (deadline strictly past -> OVERDUE)
    for c in db.cases.values():
        if c.rfe_status == "ISSUED" and c.rfe_deadline is not None \
                and c.rfe_deadline < new_now:
            c.rfe_status = "OVERDUE"
            bump(c)
    # 3. Promotion offer expiry (strictly past -> auto-declined, then re-promote)
    for e in list(db.enrollments.values()):
        if e.status == "PENDING_PROMOTION" and e.offer_expires_at is not None \
                and e.offer_expires_at < new_now:
            section = db.sections.get(e.class_section_id)
            e.status = "WITHDRAWN"
            e.offer_expires_at = None
            bump(e)
            if section is not None:
                section.pending_promotion_count -= 1
                bump(section)
                run_promotion_selector(section)
