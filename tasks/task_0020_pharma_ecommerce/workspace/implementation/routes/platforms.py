"""Platforms — create, get, advance clock."""

from __future__ import annotations

from flask import Blueprint, request

from db import (
    EPOCH_ISO,
    db,
    new_id,
    parse_iso,
    platform_clock,
    serialize,
)
from errors import err
from lookups import get_platform
from middleware import require_roles
from response import success_object
from services.clock import advance_clock
from validate import require_field, require_json

bp = Blueprint("platforms", __name__)


@bp.post("/pharma-platforms")
@require_roles("PlatformAdmin")
def create_platform():
    body = require_json(request.get_json(silent=True))
    name = require_field(body, "name", kind=str)
    jurisdiction = require_field(body, "jurisdiction", kind=str)
    regulatory_endpoint = require_field(body, "regulatory_endpoint", kind=str)

    row = {
        "id": new_id(),
        "name": name,
        "jurisdiction": jurisdiction,
        "regulatory_endpoint": regulatory_endpoint,
        "current_clock_iso": EPOCH_ISO,
        "created_at": EPOCH_ISO,
        "updated_at": EPOCH_ISO,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.platforms[row["id"]] = row
    return success_object(serialize(row)), 201


@bp.get("/pharma-platforms/<pid>")
@require_roles(
    "PlatformAdmin",
    "VendorAdmin",
    "PrescriptionReviewer",
    "PharmacistReReviewer",
    "Customer",
    "RegulatoryGateway",
)
def get_platform_route(pid: str):
    p = get_platform(pid)
    return success_object(serialize(p)), 200


@bp.post("/pharma-platforms/<pid>/_clock/advance")
@require_roles("PlatformAdmin")
def advance_clock_route(pid: str):
    platform = get_platform(pid)
    body = require_json(request.get_json(silent=True))
    to_iso = require_field(body, "to_iso", kind=str)
    try:
        new_dt = parse_iso(to_iso)
    except Exception as exc:
        raise err("ERR_INVALID_REQUEST", f"Invalid to_iso: {exc}")
    cur_dt = parse_iso(platform_clock(platform))
    if new_dt <= cur_dt:
        raise err(
            "ERR_INVALID_REQUEST",
            "to_iso must be strictly greater than current_clock_iso.",
        )
    advance_clock(platform, new_dt)
    return success_object(serialize(platform)), 200
