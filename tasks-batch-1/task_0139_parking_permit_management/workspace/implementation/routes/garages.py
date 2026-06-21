"""Garage endpoints + garage-scoped reverse-reachability lists."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import get_json_body, require_auth
from response import ok_object
from services.common import (
    lookup,
    list_response,
    require_enum,
    require_string,
)
from services.serialize import public

bp = Blueprint("garages", __name__)

GATE_MODES = {"PERMIT_OR_TRANSIENT", "PERMIT_ONLY", "CLOSED"}
ALL_ROLES = ["FacilityAdmin", "EnforcementOfficer", "Merchant", "Motorist"]


@bp.post("/parking/garages")
def create_garage():
    require_auth(["FacilityAdmin"])()
    body = get_json_body()
    name = require_string(body, "name")
    timezone = body.get("timezone")
    if timezone is None:
        timezone = "UTC"
    elif not isinstance(timezone, str) or timezone == "":
        raise APIError(ERR_INVALID_REQUEST, 400, "timezone must be a non-empty string")
    gate_mode = require_enum(body, "gate_mode", GATE_MODES, required=False, default="PERMIT_OR_TRANSIENT")

    g = db.stamp_common(
        {
            "name": name,
            "timezone": timezone,
            "gate_mode": gate_mode,
            "total_space_count": 0,
            "occupied_count": 0,
        }
    )
    db.garages[g["id"]] = g
    return ok_object(public(g), 201)


@bp.get("/parking/garages/<gid>")
def read_garage(gid):
    require_auth(ALL_ROLES)()
    g = lookup(db.garages, gid)
    return ok_object(public(g), 200)


@bp.patch("/parking/garages/<gid>")
def update_garage(gid):
    require_auth(["FacilityAdmin"])()
    g = lookup(db.garages, gid)
    body = get_json_body()
    gate_mode = require_enum(body, "gate_mode", GATE_MODES, required=True)
    g["gate_mode"] = gate_mode
    db.bump(g)
    return ok_object(public(g), 200)


# ---- garage-scoped lists ---------------------------------------------------


@bp.get("/parking/garages/<gid>/zones")
def list_garage_zones(gid):
    require_auth(ALL_ROLES)()
    lookup(db.garages, gid)
    items = [z for z in db.zones.values() if z["garage_id"] == gid]
    return list_response(items, request.args)


@bp.get("/parking/garages/<gid>/event-pricing")
def list_garage_event_pricing(gid):
    require_auth(["FacilityAdmin", "EnforcementOfficer"])()
    lookup(db.garages, gid)
    items = [e for e in db.event_pricing.values() if e["garage_id"] == gid]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return list_response(items, request.args)


@bp.get("/parking/garages/<gid>/merchants")
def list_garage_merchants(gid):
    require_auth(["FacilityAdmin"])()
    lookup(db.garages, gid)
    items = [m for m in db.merchants.values() if m["garage_id"] == gid]
    return list_response(items, request.args)


@bp.get("/parking/garages/<gid>/sessions")
def list_garage_sessions(gid):
    require_auth(["FacilityAdmin", "EnforcementOfficer"])()
    lookup(db.garages, gid)
    items = [s for s in db.sessions.values() if s["garage_id"] == gid]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response(items, request.args)


@bp.get("/parking/garages/<gid>/citations")
def list_garage_citations(gid):
    require_auth(["FacilityAdmin", "EnforcementOfficer"])()
    lookup(db.garages, gid)
    items = [c for c in db.citations.values() if c["garage_id"] == gid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items, request.args)


@bp.get("/parking/garages/<gid>/validations")
def list_garage_validations(gid):
    require_auth(["FacilityAdmin", "Merchant"])()
    lookup(db.garages, gid)
    items = [v for v in db.validations.values() if v["garage_id"] == gid]
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    return list_response(items, request.args)


@bp.get("/parking/garages/<gid>/plate-reads")
def list_garage_plate_reads(gid):
    require_auth(["FacilityAdmin", "EnforcementOfficer"])()
    lookup(db.garages, gid)
    items = [r for r in db.plate_reads.values() if r["garage_id"] == gid]
    outcome = request.args.get("enforcement_outcome")
    if outcome is not None:
        items = [r for r in items if r["enforcement_outcome"] == outcome]
    return list_response(items, request.args)
