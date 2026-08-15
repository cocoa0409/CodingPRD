"""Logical clock + retention sweep endpoints."""

from flask import Blueprint

from db import db, clock_set, clock_now, fmt_iso, parse_iso
from middleware import get_auth, require_role
from response import success_object
from services.validate import body, req_datetime
from services.entities import touch
from errors import err400, ERR_INVALID_REQUEST

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = get_auth()
    require_role(role, {"LPAdmin"})
    data = body()
    to_iso8601 = req_datetime(data, "to_iso8601")
    clock_set(parse_iso(to_iso8601))
    return success_object({"current_utc": fmt_iso(clock_now())})


@bp.route("/ops/retention-sweep", methods=["POST"])
def retention_sweep():
    user_id, role = get_auth()
    require_role(role, {"LPAdmin"})
    now = clock_now()

    # Phase 1: purge items already EXPIRED at sweep start.
    to_purge = [item for item in db.evidence_items.values()
                if item["status"] == "EXPIRED"]
    for item in to_purge:
        item["status"] = "PURGED"
        touch(item)

    # Phase 2: expire eligible ACTIVE items.
    expired_count = 0
    closed_states = {"CLOSED_SUBSTANTIATED", "CLOSED_UNSUBSTANTIATED", "CLOSED_REFERRED"}
    for item in list(db.evidence_items.values()):
        if item["status"] != "ACTIVE":
            continue
        if item["legal_hold"]:
            continue
        case = db.cases.get(item["case_id"])
        if case is None or case["status"] not in closed_states:
            continue
        ru = item.get("retention_until")
        if ru is None:
            continue  # CASE_HOLD while case open — not eligible
        if now > parse_iso(ru):  # strictly greater
            item["status"] = "EXPIRED"
            touch(item)
            expired_count += 1

    return success_object({
        "purged_count": len(to_purge),
        "expired_count": expired_count,
    })
