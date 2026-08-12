"""Single-resource reads + filtered lists for entries, audits, qualifications,
and the test-driving logical clock (mounted outside /scheduling)."""

from flask import Blueprint, request

import db
import serializers as ser
from auth import require_role, body
from envelope import success_object, success_list, paginate
from errors import invalid_request
from util import parse_iso
from validate import get_or_404, req_field

bp = Blueprint("reads", __name__)


@bp.get("/scheduling/schedule-entries/<eid>")
def get_entry(eid):
    require_role("Administrator", "Counselor", "Student")
    return success_object(ser.schedule_entry(
        get_or_404(db.schedule_entries, eid)))


@bp.get("/scheduling/schedule-entries")
def list_entries():
    require_role("Administrator", "Counselor")
    rows = list(db.schedule_entries.values())
    for param in ("term_id", "section_id", "student_id", "state"):
        v = request.args.get(param)
        if v is not None:
            rows = [e for e in rows if e[param] == v]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list([ser.schedule_entry(e) for e in page],
                        limit, offset, total)


@bp.get("/scheduling/credit-audits/<aid>")
def get_audit(aid):
    require_role("Administrator", "Counselor")
    return success_object(ser.credit_audit(get_or_404(db.credit_audits, aid)))


@bp.get("/scheduling/credit-audits")
def list_audits():
    require_role("Administrator", "Counselor")
    rows = list(db.credit_audits.values())
    for param in ("student_id", "term_id"):
        v = request.args.get(param)
        if v is not None:
            rows = [a for a in rows if a[param] == v]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list([ser.credit_audit(a) for a in page],
                        limit, offset, total)


@bp.get("/scheduling/qualifications/<qid>")
def get_qualification(qid):
    require_role("Administrator", "Counselor")
    return success_object(ser.qualification(
        get_or_404(db.qualifications, qid)))


@bp.get("/scheduling/qualifications")
def list_qualifications():
    require_role("Administrator", "Counselor")
    rows = list(db.qualifications.values())
    for param in ("teacher_id", "course_id"):
        v = request.args.get(param)
        if v is not None:
            rows = [q for q in rows if q[param] == v]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list([ser.qualification(q) for q in page],
                        limit, offset, total)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_role("Administrator")
    data = body()
    raw = req_field(data, "to_iso8601")
    try:
        parse_iso(raw)
    except ValueError:
        raise invalid_request("to_iso8601 must be an ISO8601 timestamp")
    db.clock.set(raw)
    return success_object({"current_utc": db.clock.current_iso})
