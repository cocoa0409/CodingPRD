"""Test-driving logical clock: POST /compliance/_clock/set_current_utc.

Advancing the clock runs the two expiry sweeps: APPROVED licenses whose
valid_until is strictly before the current date -> EXPIRED; ACTIVE access
grants whose end_date is on or before the current date -> EXPIRED (each
expired grant decrements its party's active_grant_count)."""

import re
from datetime import datetime, timezone

from flask import Blueprint

import db
from errors import ApiError, ERR_VALIDATION
from middleware import auth, get_body, no_unknown, need
from response import ok

bp = Blueprint("clock", __name__)

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_iso8601(value):
    if not isinstance(value, str):
        raise ApiError(ERR_VALIDATION, "to_iso8601 must be an ISO 8601 string", 400)
    try:
        if _DATE_ONLY_RE.match(value):
            dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        raise ApiError(ERR_VALIDATION, "to_iso8601 must be a valid ISO 8601 instant", 400)
    return dt.astimezone(timezone.utc)


@bp.post("/compliance/_clock/set_current_utc")
def set_current_utc():
    auth()
    body = get_body()
    no_unknown(body, {"to_iso8601"})
    raw = need(body, "to_iso8601")
    dt = _parse_iso8601(raw)
    db.set_clock(dt)
    today = db.today()
    # License expiry sweep: APPROVED and current date strictly past valid_until
    for license_ in db.LICENSES.values():
        if license_["status"] == "APPROVED" and today > license_["valid_until"]:
            license_["status"] = "EXPIRED"
            db.touch(license_)
    # Access grant expiry sweep: ACTIVE and current date on/after end_date
    for grant in db.GRANTS.values():
        if grant["status"] == "ACTIVE" and today >= grant["end_date"]:
            grant["status"] = "EXPIRED"
            db.touch(grant)
            party = db.PARTIES.get(grant["party_id"])
            if party is not None:
                party["active_grant_count"] -= 1
                db.touch(party)
    return ok({"current_utc": raw}, "object", 200)
