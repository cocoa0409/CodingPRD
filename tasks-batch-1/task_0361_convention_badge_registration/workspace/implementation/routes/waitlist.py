"""WaitlistEntry (lottery) endpoints (PRD §3.8)."""
from flask import Blueprint, request

import common
import db
import errors
import util
from middleware import authenticate, authorize
from services import calc, lookup
import response

bp = Blueprint("waitlist", __name__)

ALL_READ = {"ConventionAdmin", "RegistrationAgent", "Attendee"}


@bp.route("/conventions/<cid>/waitlist", methods=["POST"])
def create_waitlist_entry(cid):
    user_id, role = authenticate()
    authorize(role, {"Attendee", "RegistrationAgent"})
    conv = lookup.convention(cid)
    body = common.get_body()

    # Existence: body FK attendee_id (PRD §2.8).
    attendee_id = common.require_str(body, "attendee_id")
    attendee = lookup.attendee(attendee_id)

    # Ownership: Attendee enters only on its own behalf (PRD §2.1).
    lookup.require_attendee_owns(role, user_id, attendee_id)

    # Banned check (PRD §2.9 step 4).
    if attendee["status"] == "BANNED":
        raise errors.err(errors.ERR_ATTENDEE_BANNED, "Attendee is banned")

    # (12) duplicate waitlist: at most one ENTERED per (convention, attendee) — PRD §3.8.
    for e in db.waitlist_entries.values():
        if e["convention_id"] == cid and e["attendee_id"] == attendee_id and e["status"] == "ENTERED":
            raise errors.err(errors.ERR_DUPLICATE_WAITLIST, "Duplicate waitlist entry")

    # (13) posture gating: waitlist requires OPEN or SOLD_OUT (PRD §3.8).
    if conv["posture"] == "CLOSED":
        raise errors.err(errors.ERR_POSTURE_BLOCKED, "Convention is CLOSED")

    # (18) well-formedness.
    requested_quantity = common.require_int(body, "requested_quantity", minimum=1)
    group_size = common.require_int(body, "group_size", minimum=1)

    row = common.common_fields()
    created_dt = util.parse_iso(row["created_at"])
    lottery_open = util.parse_iso(conv["lottery_open_utc"])
    score = calc.priority_score(attendee["loyalty_tier"], created_dt, lottery_open, group_size)

    row.update({
        "convention_id": cid,
        "attendee_id": attendee_id,
        "requested_quantity": requested_quantity,
        "group_size": group_size,
        "priority_score": score,
        "status": "ENTERED",
    })
    db.waitlist_entries[row["id"]] = row
    return response.success(common.serialize(row), 201)


@bp.route("/conventions/<cid>/waitlist", methods=["GET"])
def list_convention_waitlist(cid):
    _, role = authenticate()
    authorize(role, ALL_READ)
    conv = lookup.convention(cid)
    rows = [e for e in db.waitlist_entries.values() if e["convention_id"] == conv["id"]]
    attendee_filter = request.args.get("attendee_id")
    if attendee_filter is not None:
        rows = [e for e in rows if e["attendee_id"] == attendee_filter]
    items, limit, offset, total = common.paginate(rows)
    return response.success_list(items, limit, offset, total)


@bp.route("/waitlist-entries", methods=["GET"])
def list_waitlist_entries():
    _, role = authenticate()
    authorize(role, ALL_READ)
    rows = list(db.waitlist_entries.values())
    attendee_filter = request.args.get("attendee_id")
    conv_filter = request.args.get("convention_id")
    if attendee_filter is not None:
        rows = [e for e in rows if e["attendee_id"] == attendee_filter]
    if conv_filter is not None:
        rows = [e for e in rows if e["convention_id"] == conv_filter]
    items, limit, offset, total = common.paginate(rows)
    return response.success_list(items, limit, offset, total)


@bp.route("/waitlist-entries/<wid>", methods=["GET"])
def get_waitlist_entry(wid):
    _, role = authenticate()
    authorize(role, ALL_READ)
    e = lookup.waitlist_entry(wid)
    return response.success(common.serialize(e), 200)
