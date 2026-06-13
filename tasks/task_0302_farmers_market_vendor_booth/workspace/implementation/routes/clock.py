"""Test-driving clock (§3.9): set current UTC, sweep VERIFIED permits to EXPIRED."""
from datetime import datetime, timezone

from flask import Blueprint

from common import touch, require_fields, req_str
from db import db
from errors import err
from middleware import get_auth, require_role, get_json_body
from response import success
from services import derived

bp = Blueprint("clock", __name__)


def _parse_iso(value):
    v = value
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_auth()
    require_role(role, {"MarketAdmin"})
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    to_iso = req_str(body, "to_iso8601")
    dt = _parse_iso(to_iso)
    db.clock.set(dt)

    # Sweep permits: VERIFIED with expiry_date < current date -> EXPIRED.
    today = db.clock.today_date()
    affected_vendors = set()
    for p in db.permits.values():
        if p["status"] == "VERIFIED" and p["expiry_date"] < today:
            p["status"] = "EXPIRED"
            touch(p)
            affected_vendors.add(p["vendor_id"])
    for vid in affected_vendors:
        v = db.vendors.get(vid)
        if v:
            derived.recompute_vendor_permit_ok(v)

    return success({}, 200)
