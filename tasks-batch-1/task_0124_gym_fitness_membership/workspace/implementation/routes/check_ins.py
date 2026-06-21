"""CheckIn (turnstile) endpoints (PRD §2.8, §3.10, §3.11)."""
from flask import Blueprint, request

import db
import errors
import lookups
import models
from middleware import authenticate, require_role
from response import success
from services import member_ops
from util import (require_str, parse_pagination, paginate)

bp = Blueprint("check_ins", __name__)


@bp.route("/check-ins", methods=["POST"])
def create_check_in():
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    body = request.get_json(silent=True) or {}

    location_id = require_str(body, "location_id")
    member_id = body.get("member_id") if isinstance(body, dict) else None
    guest_pass_id = body.get("guest_pass_id") if isinstance(body, dict) else None

    # Exactly one of member_id / guest_pass_id (PRD §3.11).
    has_member = member_id is not None
    has_guest = guest_pass_id is not None
    if has_member == has_guest:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Supply exactly one of member_id or guest_pass_id")

    # Existence left-to-right: location, then the supplied discriminator.
    location = lookups.get_location(location_id)

    if has_member:
        member = lookups.get_member(member_id)
        # Suspension/standing gate (priority 10).
        if not (member["membership_status"] == "ACTIVE" and member["dues_status"] != "SUSPENDED"):
            errors.raise_error(errors.ERR_ACCESS_DENIED_SUSPENDED, "Member may not enter")
        # Occupancy gate (priority 11).
        if models.current_occupancy(location_id) >= location["occupancy_cap"]:
            errors.raise_error(errors.ERR_OCCUPANCY_FULL, "Location is at capacity")

        rec = _make_checkin(location_id, member_id, None, "MEMBER")
        return success(models.serialize_check_in(rec), status=201)

    # Guest entry: redeem the pass.
    gp = lookups.get_guest_pass(guest_pass_id)
    # Pass must be ISSUED (state validity, priority 8).
    if gp["status"] != "ISSUED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Guest pass is not ISSUED")
    sponsor = db.store.members.get(gp["member_id"])
    # Sponsor standing gate (priority 10).
    if sponsor is None or not (sponsor["membership_status"] == "ACTIVE" and sponsor["dues_status"] != "SUSPENDED"):
        errors.raise_error(errors.ERR_ACCESS_DENIED_SUSPENDED, "Sponsor standing blocks entry")
    # Occupancy gate (priority 11).
    if models.current_occupancy(location_id) >= location["occupancy_cap"]:
        errors.raise_error(errors.ERR_OCCUPANCY_FULL, "Location is at capacity")
    # Expiry gate (priority 22).
    if db.now() > gp["expires_at"]:
        errors.raise_error(errors.ERR_GUEST_PASS_EXPIRED, "Guest pass has expired")

    gp["status"] = "REDEEMED"
    models.touch(gp)
    rec = _make_checkin(location_id, None, guest_pass_id, "GUEST")
    return success(models.serialize_check_in(rec), status=201)


@bp.route("/check-ins/<check_in_id>", methods=["GET"])
def get_check_in(check_in_id):
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    rec = lookups.get_check_in(check_in_id)
    return success(models.serialize_check_in(rec), status=200)


@bp.route("/check-ins", methods=["GET"])
def list_check_ins():
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    items = list(db.store.check_ins.values())
    location_id = request.args.get("location_id")
    member_id = request.args.get("member_id")
    guest_pass_id = request.args.get("guest_pass_id")
    status = request.args.get("status")
    if location_id is not None:
        items = [c for c in items if c["location_id"] == location_id]
    if member_id is not None:
        items = [c for c in items if c["member_id"] == member_id]
    if guest_pass_id is not None:
        items = [c for c in items if c["guest_pass_id"] == guest_pass_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    limit, offset = parse_pagination(request.args)
    page, pagination = paginate(items, limit, offset)
    return success([models.serialize_check_in(c) for c in page], status=200, pagination=pagination)


@bp.route("/check-ins/<check_in_id>/checkout", methods=["POST"])
def checkout(check_in_id):
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    rec = lookups.get_check_in(check_in_id)
    if rec["status"] != "OPEN":
        errors.raise_error(errors.ERR_INVALID_STATE, "Check-in is not OPEN")
    rec["status"] = "CLOSED"
    # current_occupancy is derived from OPEN check-ins (never below zero) — by
    # closing this one the derived count drops by one automatically.
    return success(models.serialize_check_in(rec), status=200)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _make_checkin(location_id, member_id, guest_pass_id, actor_kind):
    rec = models.stamp_new({
        "location_id": location_id,
        "member_id": member_id,
        "guest_pass_id": guest_pass_id,
        "actor_kind": actor_kind,
        "status": "OPEN",
    }, versioned=False)
    db.store.check_ins[rec["id"]] = rec
    return rec
