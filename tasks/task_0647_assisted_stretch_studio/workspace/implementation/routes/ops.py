"""Logical clock + no-show sweep (PRD §2.8, §3.5, §3.6, §3.8)."""
from flask import Blueprint, request

from db import store
from errors import err, ERR_VALIDATION
from middleware import authenticate, require_role
from response import success
from util import get_json_body, require_str, parse_iso, now_clock
from services.common import bump
from services.calc import no_show_fee_late_cancel  # noqa: F401 (kept for parity)
from services.booking import void_addons, forfeit_credit
from services.strikes import create_no_show_event, recompute_member_strike
from services import serialize

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    p = authenticate()
    require_role(p, ["StudioManager"])
    body = get_json_body()
    to_iso = require_str(body, "to_iso8601")
    parse_iso(to_iso)  # validate
    # Normalize storage to the supplied instant verbatim (kept as provided ISO).
    store.clock["current_utc"] = to_iso
    return success(serialize.clock_view(store.clock), 200)


@bp.route("/_ops/no_show_sweep", methods=["POST"])
def no_show_sweep():
    p = authenticate()
    require_role(p, ["StudioManager"])
    body = get_json_body()
    location_id = body.get("location_id")
    if location_id is not None and not isinstance(location_id, str):
        raise err(ERR_VALIDATION, "location_id must be a string.")

    clock = now_clock()
    affected_members = set()

    # Pass 1: CONFIRMED bookings past session_end_utc -> NO_SHOW.
    for b in list(store.bookings.values()):
        if location_id is not None and b["location_id"] != location_id:
            continue
        if b["schedule_status"] != "CONFIRMED":
            continue
        if clock >= parse_iso(b["session_end_utc"]):
            location = store.locations.get(b["location_id"])
            b["schedule_status"] = "NO_SHOW"
            forfeit_credit(b)
            b["fee_charged_cents"] = location["no_show_fee_cents"]
            void_addons(b["id"])
            create_no_show_event(b["member_id"], b["id"], "NO_SHOW")
            affected_members.add(b["member_id"])
            bump(b)

    # Pass 2: ACTIVE/DEPLETED credit packs past expires_utc -> EXPIRED.
    for pack in store.credit_packs.values():
        if location_id is not None and pack["location_id"] != location_id:
            continue
        if pack["status"] in ("ACTIVE", "DEPLETED") and clock >= parse_iso(pack["expires_utc"]):
            pack["status"] = "EXPIRED"
            bump(pack)

    # Pass 3: recompute strike score / suspension for every member in scope.
    # create_no_show_event already recomputed affected members; recompute all
    # (or scoped) members so rolling-window decay reinstates members whose old
    # events have aged out even without a new event.
    members = store.members.values()
    if location_id is not None:
        members = [m for m in members if m["home_location_id"] == location_id]
    for m in list(members):
        recompute_member_strike(m["id"])

    return success({}, 200)
