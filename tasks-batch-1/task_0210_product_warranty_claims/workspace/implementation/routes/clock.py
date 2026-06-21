"""Test-driving clock endpoints (PRD §3.13)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_roles
from response import ok_object
from services import common
from services.registration_svc import bump, reconcile
from services.timeutil import parse_iso

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles(["WarrantyAdmin"])
    body = common.get_json_body()
    common.require_fields(body, ["to_iso8601"])
    to_iso = common.require_str(body, "to_iso8601")
    try:
        parse_iso(to_iso)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be ISO 8601")
    db.system_clock["current_utc"] = to_iso
    return ok_object({})


@bp.post("/_clock/advance")
def advance_clock():
    require_roles(["WarrantyAdmin"])
    body = common.get_json_body()
    common.require_fields(body, ["to_iso8601"])
    to_iso = common.require_str(body, "to_iso8601")
    try:
        now = parse_iso(to_iso)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be ISO 8601")
    db.system_clock["current_utc"] = to_iso

    # expiry sweep: ACTIVE registrations strictly past warranty_end_date -> EXPIRED
    for reg in db.registrations.values():
        if reg["status"] != "ACTIVE":
            continue
        reconcile(reg)
        end = reg.get("warranty_end_date")
        if end is not None and now > parse_iso(end):
            reg["status"] = "EXPIRED"
            bump(reg)
    return ok_object({})
