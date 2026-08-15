"""Implementation logs: file observation, list, detail."""
from flask import Blueprint, g, request

from db import db, create_record
from errors import (ERR_ACCOMMODATION_NOT_ACTIVE, ERR_DEVIATION_NOTES_REQUIRED,
                    raise_err)
from middleware import body, opt_str, parse_bool_filter, req_bool, req_str, require_roles
from response import success
from routes import list_response
from services import (get_accommodation, get_plan, log_out, posture_gate,
                      school_of_plan)
from util import parse_dt

bp = Blueprint("logs", __name__)

LOG_READERS = ("District504Director", "Section504Coordinator", "SchoolPrincipal", "Teacher")


@bp.post("/implementation-logs")
@require_roles("Teacher", "Section504Coordinator")
def create_log():
    d = body()
    plan = get_plan(req_str(d, "plan_id"))
    acc = get_accommodation(req_str(d, "accommodation_id"))
    posture_gate(school_of_plan(plan))
    was_implemented = req_bool(d, "was_implemented_as_planned")
    notes = opt_str(d, "deviation_notes", None)
    if was_implemented is False and (notes is None or not notes.strip()):
        raise_err(ERR_DEVIATION_NOTES_REQUIRED,
                  "deviation_notes is required when was_implemented_as_planned is false")
    log_date = parse_dt(req_str(d, "log_date"), "log_date")
    if acc["accommodation_status"] != "ACTIVE":
        raise_err(ERR_ACCOMMODATION_NOT_ACTIVE,
                  "Accommodation must be ACTIVE for implementation logging")
    rec = create_record(db.logs, {
        "plan_id": plan["id"],
        "accommodation_id": acc["id"],
        "logged_by_staff_id": g.user_id,
        "log_date": log_date,
        "was_implemented_as_planned": was_implemented,
        "deviation_notes": notes,
    })
    return success(log_out(rec), 201)


@bp.get("/implementation-logs")
@require_roles(*LOG_READERS)
def list_logs():
    items = list(db.logs.values())
    plan_id = request.args.get("plan_id")
    acc_id = request.args.get("accommodation_id")
    impl = parse_bool_filter("was_implemented_as_planned")
    if plan_id is not None:
        items = [l for l in items if l["plan_id"] == plan_id]
    if acc_id is not None:
        items = [l for l in items if l["accommodation_id"] == acc_id]
    if impl is not None:
        items = [l for l in items if l["was_implemented_as_planned"] == impl]
    return list_response(items, log_out)


@bp.get("/implementation-logs/<logId>")
@require_roles(*LOG_READERS)
def get_log_detail(logId):
    from errors import ERR_NOT_FOUND
    from services import _get
    return success(log_out(_get(db.logs, logId, ERR_NOT_FOUND, "ImplementationLog")), 200)
