from flask import Blueprint

import errors
from errors import err
from db import db
from clock import iso_millis, parse_iso
from middleware import get_auth, require_role
from response import ok_raw
from validate import body

bp = Blueprint("clock", __name__)

ALL_ROLES = {"ScreeningOfficer", "LabTech", "CatalogManager", "ComplianceOfficer", "BillingClerk", "Recipient"}


@bp.post("/_clock/set_current_utc")
def set_clock():
    _uid, role = get_auth()
    require_role(role, ALL_ROLES)
    data = body()
    to_iso = data.get("to_iso8601")
    if not isinstance(to_iso, str):
        raise err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be an ISO8601 string")
    try:
        parse_iso(to_iso)
    except (ValueError, TypeError):
        raise err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be an ISO8601 string")
    db.clock.set(to_iso)
    return ok_raw({"current_utc": iso_millis(db.now())})
