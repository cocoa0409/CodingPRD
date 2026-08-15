from flask import Blueprint, request

import db
from calc import add_days
from errors import ApiError
from middleware import authenticate, require_role, locked
from response import ok, ok_list
from serializers import ser_audit
from validators import pagination, apply_filters

bp = Blueprint("audits", __name__)

CURE_WINDOW_DAYS = 45


def _get_audit(aid):
    a = db.audits.get(aid)
    if a is None:
        raise ApiError("ERR_AUDIT_NOT_FOUND", 404,
                       "attachment audit id does not resolve")
    return a


@bp.get("/pole-program/attachment-audits")
def list_audits():
    authenticate()
    limit, offset = pagination()
    items = apply_filters(db.audits.values(), [
        ("pole_id", request.args.get("pole_id")),
        ("inspection_task_id", request.args.get("inspection_task_id")),
    ])
    page = items[offset:offset + limit]
    return ok_list([ser_audit(a) for a in page], len(items), limit, offset)


@bp.get("/pole-program/attachment-audits/<aid>")
def get_audit(aid):
    authenticate()
    return ok(ser_audit(_get_audit(aid)), 200)


@bp.post("/pole-program/attachment-audits/<aid>/adjudicate")
@locked
def adjudicate_audit(aid):
    uid, role = authenticate()
    require_role(role, "ProgramManager")
    audit = _get_audit(aid)
    if audit["audit_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "adjudicate requires audit.audit_status == SUBMITTED")
    n = db.clock_now()
    audit["adjudicated_at"] = n
    audit["audit_status"] = "ADJUDICATED"
    if audit["unauthorized_count"] > 0:
        # NONE -> DETECTED -> NOTIFIED within the same adjudication.
        audit["violation_status"] = "NOTIFIED"
        audit["cure_deadline"] = add_days(n, CURE_WINDOW_DAYS)
    db.touch(audit)
    return ok(ser_audit(audit), 200)


@bp.post("/pole-program/attachment-audits/<aid>/mark-cured")
@locked
def mark_cured(aid):
    uid, role = authenticate()
    require_role(role, "AttacherRep")
    audit = _get_audit(aid)
    if audit["violation_status"] != "NOTIFIED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "mark-cured requires violation_status == NOTIFIED")
    n = db.clock_now()
    if audit["cure_deadline"] is not None and n > audit["cure_deadline"]:
        raise ApiError("ERR_CURE_DEADLINE_PASSED", 422,
                       "mark-cured attempted after cure_deadline")
    audit["cured_at"] = n
    audit["violation_status"] = "CURED"
    db.touch(audit)
    return ok(ser_audit(audit), 200)
