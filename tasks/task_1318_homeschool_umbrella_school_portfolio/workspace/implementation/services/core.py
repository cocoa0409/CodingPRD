"""Cross-aggregate helpers: graph navigation, touching/mutation, ownership roots."""
import uuid

import clock
import db
from errors import raise_err


def new_id():
    return str(uuid.uuid4())


_SEQ = [0]


def _next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


def make_record(extra):
    """New entity record with common system fields."""
    ts = clock.now_iso()
    rec = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
           "_seq": _next_seq()}
    rec.update(extra)
    return rec


def touch(rec):
    rec["updated_at"] = clock.now_iso()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Graph navigation (return None when any link missing)
# ---------------------------------------------------------------------------

def enrollment_of_student(student):
    return None  # not a single enrollment; placeholder for clarity


def get_enrollment(eid):
    return db.enrollments.get(eid)


def family_of_student(student):
    return db.families.get(student["family_id"]) if student else None


def student_of_enrollment(enrollment):
    return db.students.get(enrollment["student_id"]) if enrollment else None


def family_of_enrollment(enrollment):
    st = student_of_enrollment(enrollment)
    return family_of_student(st)


def year_of_enrollment(enrollment):
    return db.academic_years.get(enrollment["academic_year_id"]) if enrollment else None


def enrollment_of_notice(notice):
    return db.enrollments.get(notice["enrollment_id"]) if notice else None


def enrollment_of_plan(plan):
    return db.enrollments.get(plan["enrollment_id"]) if plan else None


def enrollment_of_attendance(entry):
    return db.enrollments.get(entry["enrollment_id"]) if entry else None


def enrollment_of_portfolio(portfolio):
    return db.enrollments.get(portfolio["enrollment_id"]) if portfolio else None


def portfolio_of_evaluation(ev):
    return db.portfolios.get(ev["portfolio_id"]) if ev else None


def enrollment_of_registration(reg):
    return db.enrollments.get(reg["enrollment_id"]) if reg else None


def session_of_registration(reg):
    return db.exam_sessions.get(reg["exam_session_id"]) if reg else None


def enrollment_of_credit(credit):
    return db.enrollments.get(credit["enrollment_id"]) if credit else None


def enrollment_of_coop_enrollment(ce):
    return db.enrollments.get(ce["enrollment_id"]) if ce else None


def class_of_coop_enrollment(ce):
    return db.coop_classes.get(ce["coop_class_id"]) if ce else None


def student_of_grad_app(app):
    return db.students.get(app["student_id"]) if app else None


def year_of_exam_session(sess):
    return db.academic_years.get(sess["academic_year_id"]) if sess else None


def year_of_coop_class(cls):
    return db.academic_years.get(cls["academic_year_id"]) if cls else None


def year_of_report(rep):
    return db.academic_years.get(rep["academic_year_id"]) if rep else None


def root_family_id(kind, entity_id):
    """Resolve a path segment (kind, id) to the owning Family.id, or None."""
    if kind == "family":
        fam = db.families.get(entity_id)
        return fam["id"] if fam else None
    if kind == "student":
        st = db.students.get(entity_id)
        return st["family_id"] if st else None
    if kind == "enrollment":
        en = db.enrollments.get(entity_id)
        st = student_of_enrollment(en) if en else None
        return st["family_id"] if st else None
    if kind == "notice":
        n = db.notices.get(entity_id)
        en = enrollment_of_notice(n) if n else None
        return root_family_id("enrollment", en["id"]) if en else None
    if kind == "curriculum_plan":
        p = db.curriculum_plans.get(entity_id)
        en = enrollment_of_plan(p) if p else None
        return root_family_id("enrollment", en["id"]) if en else None
    if kind == "attendance_entry":
        a = db.attendance_entries.get(entity_id)
        en = enrollment_of_attendance(a) if a else None
        return root_family_id("enrollment", en["id"]) if en else None
    if kind == "portfolio":
        p = db.portfolios.get(entity_id)
        en = enrollment_of_portfolio(p) if p else None
        return root_family_id("enrollment", en["id"]) if en else None
    if kind == "evaluation":
        ev = db.evaluations.get(entity_id)
        pf = portfolio_of_evaluation(ev) if ev else None
        return root_family_id("portfolio", pf["id"]) if pf else None
    if kind == "test_registration":
        r = db.test_registrations.get(entity_id)
        en = enrollment_of_registration(r) if r else None
        return root_family_id("enrollment", en["id"]) if en else None
    if kind == "course_credit":
        c = db.course_credits.get(entity_id)
        en = enrollment_of_credit(c) if c else None
        return root_family_id("enrollment", en["id"]) if en else None
    if kind == "coop_enrollment":
        ce = db.coop_enrollments.get(entity_id)
        en = enrollment_of_coop_enrollment(ce) if ce else None
        return root_family_id("enrollment", en["id"]) if en else None
    if kind == "graduation_application":
        g = db.graduation_applications.get(entity_id)
        st = student_of_grad_app(g) if g else None
        return st["family_id"] if st else None
    return None


def sorted_by_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def paginate(records):
    """Apply limit/offset query params with defaults; returns (page, limit, offset, total)."""
    from flask import request
    from errors import raise_err
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise_err("ERR_INVALID_REQUEST", "offset must be >= 0")
    total = len(records)
    page = records[offset:offset + limit]
    return page, limit, offset, total
