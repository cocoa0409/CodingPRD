"""Site routes (PRD §3.1, §4)."""
from flask import Blueprint

import db
import serialize
from middleware import authenticate, authorize, get_json_body
from helpers import require_str, opt_str, require_int, parse_pagination, paginate
from response import object_response, array_response

bp = Blueprint("sites", __name__)


@bp.post("/sites")
def create_site():
    _, role = authenticate()
    authorize(role, ["MaintenanceManager"])
    body = get_json_body()
    name = require_str(body, "name")
    if len(name) > 120:
        from errors import invalid_request
        raise invalid_request("name must be at most 120 characters.")
    timezone = opt_str(body, "timezone", "UTC")
    budget = require_int(body, "maintenance_budget_cents", minimum=0)
    with db.LOCK:
        rec = db.new_record()
        rec.update({
            "name": name,
            "timezone": timezone,
            "maintenance_budget_cents": budget,
            "budget_spent_cents": 0,
        })
        db.sites[rec["id"]] = rec
        return object_response(serialize.site(rec), 201)


@bp.get("/sites/<sid>")
def get_site(sid):
    _, role = authenticate()
    authorize(role, ["MaintenanceManager", "Planner", "WarrantyAdmin"])
    with db.LOCK:
        rec = db.sites.get(sid)
        if rec is None:
            from errors import not_found
            raise not_found()
        return object_response(serialize.site(rec), 200)


@bp.get("/sites")
def list_sites():
    _, role = authenticate()
    authorize(role, ["MaintenanceManager", "Planner", "WarrantyAdmin"])
    limit, offset = parse_pagination()
    with db.LOCK:
        items = sorted(db.sites.values(), key=lambda r: r["_seq"])
        total = len(items)
        page = paginate(items, limit, offset)
        return array_response([serialize.site(r) for r in page], limit, offset, total)
