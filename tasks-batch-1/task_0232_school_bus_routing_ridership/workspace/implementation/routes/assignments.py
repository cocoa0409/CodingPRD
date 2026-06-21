"""DriverAssignment read endpoints (creation lives in routes_rt.py). PRD §3.5."""

from flask import Blueprint, request

from db import DB
from middleware import authenticate, require_role
from response import ok, ok_list
from services.common import parse_pagination, sorted_by_creation, paginate
from services.domain import assignment_public
from services.lookup import get_assignment

bp = Blueprint("assignments", __name__)


@bp.get("/driver-assignments/<assignment_id>")
def get_assignment_ep(assignment_id):
    p = authenticate()
    require_role(p, {"TransportAdmin", "Driver"})
    rec = get_assignment(assignment_id)
    return ok(assignment_public(rec), 200)


@bp.get("/driver-assignments")
def list_assignments():
    p = authenticate()
    require_role(p, {"TransportAdmin", "Driver"})
    limit, offset = parse_pagination(request.args)

    records = list(DB.driver_assignments.values())
    for field in ("route_id", "driver_id", "replaces_assignment_id", "status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]

    records = sorted_by_creation(records)
    page, total = paginate(records, limit, offset)
    return ok_list([assignment_public(r) for r in page], limit, offset, total)
