from flask import Blueprint, request

import errors
from db import db
from middleware import authenticate, require_roles
from response import success, list_success
from services import validate as V
from services.common import new_common, touch, paginate, page_slice
from services.serialize import resort_out, lift_scan_out, buddy_ticket_out, interchange_out

bp = Blueprint("resorts", __name__)

READ_ROLES = {"NetworkAdmin", "ResortOps", "RefundAdmin"}


@bp.post("/resorts")
def create_resort():
    _, role = authenticate()
    require_roles(role, {"NetworkAdmin"})
    body = V.get_body(request)
    name = V.require_str(body, "name")
    home_network = V.optional_enum(body, "home_network", {"EPIC", "IKON"}, "EPIC")
    gate_count = V.optional_int(body, "gate_count", 1, minimum=1)
    rec = new_common({
        "name": name,
        "home_network": home_network,
        "status": "OPEN",
        "gate_count": gate_count,
    })
    db.resorts[rec["id"]] = rec
    return success(resort_out(rec), status=201)


@bp.get("/resorts")
def list_resorts():
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    limit, offset = paginate(request.args)
    home_network = request.args.get("home_network")
    records = list(db.resorts.values())
    if home_network is not None:
        records = [r for r in records if r["home_network"] == home_network]
    window, total = page_slice(records, limit, offset)
    return list_success([resort_out(r) for r in window], limit, offset, total)


@bp.get("/resorts/<rid>")
def get_resort(rid):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    rec = db.resorts.get(rid)
    if rec is None:
        raise errors.not_found("Resort not found")
    return success(resort_out(rec))


@bp.post("/resorts/<rid>/suspend")
def suspend_resort(rid):
    _, role = authenticate()
    require_roles(role, {"NetworkAdmin"})
    rec = db.resorts.get(rid)
    if rec is None:
        raise errors.not_found("Resort not found")
    if rec["status"] != "OPEN":
        raise errors.invalid_state("Resort is not OPEN")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success(resort_out(rec))


# ---- FK reverse-reachability GETs scoped by resort ----

@bp.get("/resorts/<rid>/lift-scans")
def resort_lift_scans(rid):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    if db.resorts.get(rid) is None:
        raise errors.not_found("Resort not found")
    limit, offset = paginate(request.args)
    records = [s for s in db.lift_scans.values() if s["resort_id"] == rid]
    window, total = page_slice(records, limit, offset)
    return list_success([lift_scan_out(s) for s in window], limit, offset, total)


@bp.get("/resorts/<rid>/buddy-tickets")
def resort_buddy_tickets(rid):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    if db.resorts.get(rid) is None:
        raise errors.not_found("Resort not found")
    limit, offset = paginate(request.args)
    valid_date = request.args.get("valid_date")
    records = [b for b in db.buddy_tickets.values() if b["resort_id"] == rid]
    if valid_date is not None:
        records = [b for b in records if b["valid_date"] == valid_date]
    window, total = page_slice(records, limit, offset)
    return list_success([buddy_ticket_out(b) for b in window], limit, offset, total)


@bp.get("/resorts/<rid>/interchange-agreements")
def resort_interchange_agreements(rid):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    if db.resorts.get(rid) is None:
        raise errors.not_found("Resort not found")
    limit, offset = paginate(request.args)
    records = [a for a in db.interchange_agreements.values() if a["resort_id"] == rid]
    window, total = page_slice(records, limit, offset)
    return list_success([interchange_out(a) for a in window], limit, offset, total)
