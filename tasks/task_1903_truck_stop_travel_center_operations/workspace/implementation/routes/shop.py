"""Shop bays and technicians (PRD 3.7)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import authorized
from response import success_object
from routes.helpers import list_from, list_response, public
from services.core import new_record, touch
from util import fmt_dt, parse_dt
from validate import (
    get_body, query_filter, req_dt, req_int, req_str, require_path_resource,
)

bp = Blueprint("shop", __name__)

BAY_STATUSES = ["IDLE", "OCCUPIED", "MAINTENANCE"]
READ_ROLES = ["GeneralManager", "MaintenanceTech", "ShiftManager"]


# ---------------------------------------------------------------------------
# Bays
# ---------------------------------------------------------------------------

@bp.post("/sites/<sid>/bays")
def create_bay(sid):
    authorized(["GeneralManager"])
    site = require_path_resource("sites", sid)
    body = get_body()
    bay_number = req_int(body, "bay_number")
    for b in db["bays"].values():
        if b["site_id"] == site["id"] and b["bay_number"] == bay_number:
            raise_error(ERR_INVALID_REQUEST, "bay_number must be unique within the site")
    rec = new_record("bays", {
        "site_id": site["id"],
        "bay_number": bay_number,
        "status": "IDLE",
        "maintenance_blocks": [],
    })
    return success_object(public(rec), status=201)


@bp.get("/sites/<sid>/bays")
def list_bays(sid):
    authorized(READ_ROLES)
    require_path_resource("sites", sid)
    filters = {"site_id": sid, "status": query_filter("status", BAY_STATUSES)}
    return list_response("bays", filters)


@bp.get("/bays/<rid>")
def get_bay(rid):
    authorized(READ_ROLES)
    rec = require_path_resource("bays", rid)
    return success_object(public(rec))


@bp.get("/bays/<rid>/work-orders")
def bay_work_orders(rid):
    authorized(["GeneralManager", "MaintenanceTech"])
    bay = require_path_resource("bays", rid)
    wos = [w for w in db["work_orders"].values() if w["bay_id"] == bay["id"]]
    return list_from(wos)


@bp.post("/bays/<rid>/maintenance-block")
def maintenance_block(rid):
    authorized(["GeneralManager", "MaintenanceTech"])
    bay = require_path_resource("bays", rid)
    if bay["status"] != "IDLE":
        raise_error(ERR_INVALID_STATE, "only an IDLE bay can be blocked for maintenance")
    body = get_body()
    blocked_from = req_dt(body, "blocked_from")
    blocked_to = req_dt(body, "blocked_to")
    reason = req_str(body, "reason")
    if parse_dt(blocked_to) < parse_dt(blocked_from):
        raise_error(ERR_INVALID_REQUEST, "blocked_to must not precede blocked_from")
    bay["maintenance_blocks"].append({
        "blocked_from": fmt_dt(parse_dt(blocked_from)),
        "blocked_to": fmt_dt(parse_dt(blocked_to)),
        "reason": reason,
    })
    bay["status"] = "MAINTENANCE"
    touch(bay)
    return success_object(public(bay))


@bp.post("/bays/<rid>/maintenance-clear")
def maintenance_clear(rid):
    authorized(["GeneralManager", "MaintenanceTech"])
    bay = require_path_resource("bays", rid)
    if bay["status"] != "MAINTENANCE":
        raise_error(ERR_INVALID_STATE, "only a MAINTENANCE bay can be cleared")
    bay["status"] = "IDLE"
    touch(bay)
    return success_object(public(bay))


# ---------------------------------------------------------------------------
# Technicians
# ---------------------------------------------------------------------------

@bp.post("/sites/<sid>/technicians")
def create_technician(sid):
    authorized(["GeneralManager"])
    site = require_path_resource("sites", sid)
    body = get_body()
    name = req_str(body, "name")
    rate = req_int(body, "hourly_rate_cents", positive=True)
    certs = body.get("certifications")
    if certs is None:
        certs = []
    if not isinstance(certs, list) or any(not isinstance(c, str) for c in certs):
        raise_error(ERR_INVALID_REQUEST, "certifications must be an array of strings")
    rec = new_record("technicians", {
        "site_id": site["id"],
        "name": name,
        "hourly_rate_cents": rate,
        "certifications": list(certs),
        "status": "AVAILABLE",
    })
    return success_object(public(rec), status=201)


@bp.get("/sites/<sid>/technicians")
def list_technicians(sid):
    authorized(READ_ROLES)
    require_path_resource("sites", sid)
    return list_response("technicians", {"site_id": sid})


@bp.get("/technicians/<rid>")
def get_technician(rid):
    authorized(READ_ROLES)
    rec = require_path_resource("technicians", rid)
    return success_object(public(rec))


@bp.get("/technicians/<rid>/work-orders")
def technician_work_orders(rid):
    authorized(["GeneralManager", "MaintenanceTech"])
    tech = require_path_resource("technicians", rid)
    wos = [w for w in db["work_orders"].values() if w["technician_id"] == tech["id"]]
    return list_from(wos)
