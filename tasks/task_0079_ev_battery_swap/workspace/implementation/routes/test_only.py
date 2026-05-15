"""Test-only endpoints: clock advance and no-show sweep."""

from datetime import timedelta

from flask import Blueprint

from db import DB
from errors import ERR_INVALID_INPUT, raise_error
from middleware import auth_required
from response import success_response
from services.audit import append_audit
from services.common import bump_version, get_body, require_string
from services.time_util import format_iso, parse_iso, server_now, set_clock


bp = Blueprint("test_only", __name__, url_prefix="/swap-stations")


@bp.route("/_clock/advance", methods=["POST"])
@auth_required(["PlatformAdmin"])
def clock_advance():
    body = get_body()
    to_iso = require_string(body, "to_iso")
    try:
        set_clock(to_iso)
    except ValueError:
        raise_error(ERR_INVALID_INPUT, "to_iso must be ISO 8601")
    return success_response({"now": format_iso(server_now())})


@bp.route("/_sweep/no-show", methods=["POST"])
@auth_required(["PlatformAdmin"])
def sweep_no_show():
    now = server_now()
    swept = []
    affected_members = set()

    for r in list(DB["reservations"].values()):
        if r.get("status") != "BOOKED":
            continue
        end_dt = parse_iso(r["slot_end_at"])
        if end_dt is None or now <= end_dt:
            continue
        prev = r["status"]
        r["status"] = "NO_SHOW"
        r["held_battery_id"] = None
        bump_version(r)
        append_audit("RESERVATION_CHANGE", "Reservation", r["id"], prev, "NO_SHOW")
        swept.append(r["id"])
        if r.get("member_id"):
            affected_members.add(r["member_id"])

    # Recompute no_show_count_30d per affected member and possibly set block.
    thirty_days_ago = now - timedelta(days=30)
    for member_id in affected_members:
        member = DB["members"].get(member_id)
        if member is None:
            continue
        count = 0
        for r in DB["reservations"].values():
            if r.get("member_id") != member_id:
                continue
            if r.get("status") != "NO_SHOW":
                continue
            created = parse_iso(r.get("created_at"))
            if created is None:
                continue
            if created >= thirty_days_ago:
                count += 1
        member["no_show_count_30d"] = count
        if count >= 3:
            member["reservation_blocked_until"] = format_iso(now + timedelta(hours=72))
        bump_version(member)

    return success_response({"swept_reservation_ids": swept, "swept_count": len(swept)})
