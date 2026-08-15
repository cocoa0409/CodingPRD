"""Annual procedure audits (PRD 3.7)."""

import math
from datetime import timedelta

from flask import Blueprint, request

import db
from clock import CLOCK, parse_iso, fmt
from errors import ApiError
from middleware import auth, paginate, ALL_ROLES
from response import ok, ok_list
from services import core

bp = Blueprint("procedure_audits", __name__)


@bp.route("/procedure-audits", methods=["POST"])
def create_audit():
    user_id, _ = auth(["EHSAuditor"])
    body = core.body_json()
    procedure_id = core.req_str(body, "procedure_id")
    start = core.req_dt(body, "scheduled_start")
    end = core.req_dt(body, "scheduled_end")
    if not start < end:
        raise ApiError("ERR_VALIDATION", 400,
                       "scheduled_start must be strictly before scheduled_end")
    proc = core.get_or_404("lockout_procedures", procedure_id, "LockoutProcedure")
    now = CLOCK.now()
    # Guards, in PRD 3.7 order: competency, auditor independence, double-booking.
    if not core.actor_qualified(user_id):
        raise ApiError("ERR_TRAINING_NOT_CURRENT", 409,
                       "Auditor is not a currently qualified authorized employee")
    # period_start snapshot: last completed audit, else first activation.
    period_start = proc["last_completed_audit_at"] or proc["activated_at"]
    if user_id in core.period_appliers(proc["id"], period_start, now):
        raise ApiError("ERR_AUDITOR_CONFLICT", 409,
                       "Auditor applied locks under this procedure in the audit period")
    for a in db.DB["procedure_audits"].values():
        if a["auditor_employee_id"] != user_id or a["status"] != "SCHEDULED":
            continue
        # Closed-interval overlap: touching endpoints DO conflict.
        if start <= parse_iso(a["scheduled_end"]) and parse_iso(a["scheduled_start"]) <= end:
            raise ApiError("ERR_AUDITOR_DOUBLE_BOOKED", 409,
                           "Auditor already has a SCHEDULED audit overlapping this window")
    a = core.stamp_new({
        "id": core.new_id(),
        "procedure_id": proc["id"],
        "auditor_employee_id": user_id,
        "scheduled_start": fmt(start),
        "scheduled_end": fmt(end),
        "period_start": period_start,
        "result": None,
        "employees_sampled": None,
        "completed_at": None,
        "status": "SCHEDULED",
    })
    db.DB["procedure_audits"][a["id"]] = a
    return ok(core.audit_view(a), 201)


@bp.route("/procedure-audits", methods=["GET"])
def list_audits():
    auth(ALL_ROLES)
    procedure_id = request.args.get("procedure_id")
    auditor = request.args.get("auditor_employee_id")
    status = request.args.get("status")
    items = list(db.DB["procedure_audits"].values())
    if procedure_id is not None:
        items = [a for a in items if a["procedure_id"] == procedure_id]
    if auditor is not None:
        items = [a for a in items if a["auditor_employee_id"] == auditor]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.audit_view(a) for a in page], total, limit, offset)


@bp.route("/procedure-audits/<aid>", methods=["GET"])
def get_audit(aid):
    auth(ALL_ROLES)
    a = core.get_or_404("procedure_audits", aid, "ProcedureAudit")
    return ok(core.audit_view(a))


@bp.route("/procedure-audits/<aid>/complete", methods=["POST"])
def complete_audit(aid):
    user_id, _ = auth(["EHSAuditor"])
    body = core.body_json()
    result = core.req_enum(body, "result", ("PASS", "FAIL"))
    sample = body.get("employees_sampled")
    if not isinstance(sample, list) or any(not isinstance(x, str) for x in sample):
        raise ApiError("ERR_VALIDATION", 400,
                       "employees_sampled is required and must be an array of employee ids")
    a = core.get_or_404("procedure_audits", aid, "ProcedureAudit")
    # Ownership (stage 5): only the assigned auditor completes the audit.
    if a["auditor_employee_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", 403, "Only the assigned auditor may complete the audit")
    if a["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a SCHEDULED audit can be completed")
    now = CLOCK.now()
    # calculations.audit_sample_minimum over the closed [period_start, clock] window.
    population = core.period_appliers(a["procedure_id"], a["period_start"], now)
    minimum = 0 if len(population) == 0 else max(1, math.ceil(0.25 * len(population)))
    if not set(sample) <= population or len(sample) < minimum:
        raise ApiError("ERR_SAMPLE_TOO_SMALL", 422,
                       "employees_sampled must be a subset of period lock-appliers "
                       "and meet the sample minimum")
    a["completed_at"] = fmt(now)
    a["result"] = result
    a["employees_sampled"] = sample
    a["status"] = "COMPLETED"
    core.touch(a)
    proc = db.DB["lockout_procedures"][a["procedure_id"]]
    proc["last_completed_audit_at"] = fmt(now)
    proc["audit_due_at"] = fmt(now + timedelta(days=core.WINDOW_DAYS))
    # A FAIL pushes an ACTIVE procedure into UNDER_REVISION — deliberately
    # without cancelling any sessions (PRD 3.7).
    if result == "FAIL" and proc["status"] == "ACTIVE":
        proc["status"] = "UNDER_REVISION"
    core.touch(proc)
    return ok(core.audit_view(a))
