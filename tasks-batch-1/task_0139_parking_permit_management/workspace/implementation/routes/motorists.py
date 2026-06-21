"""Motorist endpoints + motorist-scoped lists."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_DUPLICATE
from middleware import get_json_body, require_auth
from response import ok_object
from services.common import (
    list_response,
    lookup,
    normalize_plate,
    require_string,
)
from services.serialize import public

bp = Blueprint("motorists", __name__)


@bp.post("/parking/motorists")
def create_motorist():
    require_auth(["FacilityAdmin", "Motorist"])()
    body = get_json_body()
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    default_plate = require_string(body, "default_plate")

    # Email globally unique.
    for m in db.motorists.values():
        if m["email"] == email:
            raise APIError(ERR_DUPLICATE, 409, "email already registered")

    m = db.stamp_common(
        {
            "full_name": full_name,
            "email": email,
            "default_plate": normalize_plate(default_plate),
            "outstanding_balance_cents": 0,
        }
    )
    db.motorists[m["id"]] = m
    return ok_object(public(m), 201)


@bp.get("/parking/motorists/<mid>")
def read_motorist(mid):
    require_auth(["FacilityAdmin", "EnforcementOfficer", "Motorist"])()
    m = lookup(db.motorists, mid)
    return ok_object(public(m), 200)


@bp.get("/parking/motorists/<mid>/permits")
def list_motorist_permits(mid):
    require_auth(["FacilityAdmin", "Motorist"])()
    lookup(db.motorists, mid)
    items = [p for p in db.permits.values() if p["motorist_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response(items, request.args)


@bp.get("/parking/motorists/<mid>/waitlist-entries")
def list_motorist_waitlist(mid):
    require_auth(["FacilityAdmin", "Motorist"])()
    lookup(db.motorists, mid)
    items = [w for w in db.waitlist_entries.values() if w["motorist_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    return list_response(items, request.args)


@bp.get("/parking/motorists/<mid>/citations")
def list_motorist_citations(mid):
    require_auth(["FacilityAdmin", "EnforcementOfficer", "Motorist"])()
    lookup(db.motorists, mid)
    items = [c for c in db.citations.values() if c.get("motorist_id") == mid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items, request.args)


@bp.get("/parking/motorists/<mid>/appeals")
def list_motorist_appeals(mid):
    require_auth(["FacilityAdmin", "Motorist"])()
    lookup(db.motorists, mid)
    items = [a for a in db.appeals.values() if a["motorist_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(items, request.args)
