"""Staff: hire, read, list, release (with shift-cancellation compensation)."""
from flask import Blueprint

import db
from db import serialize, touch
from errors import raise_err, ERR_STAFF_INVALID_STATE
from helpers import get_or_404, paginate, qparam
from middleware import authenticate, scope_to_fair
from response import ok
from services.cascades import staff_release_cascade
from validators import get_body, reject_unknown, req_str, req_str_list

bp = Blueprint("staff", __name__)

ALL = ["StateProgramAdmin", "StateInspector", "FairManager", "RideOperator", "TicketClerk", "CrewMember"]

FUNCTIONS = ["OPERATOR", "CLERK", "CREW", "SUPERVISOR"]


@bp.post("/staff")
def create_staff():
    ctx = authenticate(["StateProgramAdmin", "FairManager"])
    body = get_body()
    reject_unknown(body, {"fair_id", "full_name", "functions"})
    fair_id = req_str(body, "fair_id")
    full_name = req_str(body, "full_name")
    functions = req_str_list(body, "functions", FUNCTIONS)
    scope_to_fair(ctx, fair_id if db.get("fairs", fair_id) else None)
    fair = get_or_404("fairs", fair_id)
    scope_to_fair(ctx, fair["id"])
    staff = db.register(
        "staff",
        {
            "fair_id": fair_id,
            "full_name": full_name,
            "functions": functions,
            "status": "ACTIVE",
            "released_at": None,
        },
    )
    return ok(serialize(staff), 201)


@bp.get("/staff/<sid>")
def get_staff(sid):
    ctx = authenticate(ALL)
    staff = get_or_404("staff", sid)
    scope_to_fair(ctx, staff["fair_id"])
    return ok(serialize(staff))


@bp.get("/staff")
def list_staff():
    authenticate(ALL)
    return paginate("staff", {"fair_id": qparam("fair_id"), "status": qparam("status")})


@bp.post("/staff/<sid>/release")
def release_staff(sid):
    ctx = authenticate(["FairManager"])
    staff = get_or_404("staff", sid)
    scope_to_fair(ctx, staff["fair_id"])
    body = get_body()
    reject_unknown(body, set())
    if staff["status"] != "ACTIVE":
        raise_err(ERR_STAFF_INVALID_STATE, "Staff member is already RELEASED")
    staff["status"] = "RELEASED"
    staff["released_at"] = db.now_iso()
    touch(staff)
    staff_release_cascade(staff)
    return ok(serialize(staff))
