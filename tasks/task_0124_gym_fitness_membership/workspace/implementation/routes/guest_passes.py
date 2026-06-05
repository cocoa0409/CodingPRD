"""GuestPass endpoints (PRD §3.10)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import constants
import errors
import lookups
import models
from middleware import authenticate, require_role, require_owner
from response import success
from util import (require_str, parse_pagination, paginate)

bp = Blueprint("guest_passes", __name__)


@bp.route("/guest-passes", methods=["POST"])
def issue_guest_pass():
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    body = request.get_json(silent=True) or {}

    member_id = require_str(body, "member_id")
    guest_name = require_str(body, "guest_name")
    location_id = require_str(body, "location_id")

    require_owner(caller, member_id)

    # Existence left-to-right: member then location.
    member = lookups.get_member(member_id)
    location = lookups.get_location(location_id)

    # Fiscal: guest_passes_remaining >= 1 (priority 19).
    if member["guest_passes_remaining"] < 1:
        errors.raise_error(errors.ERR_NO_GUEST_PASSES, "No guest passes remaining")

    now = db.now()
    rec = models.stamp_new({
        "member_id": member_id,
        "guest_name": guest_name,
        "location_id": location_id,
        "status": "ISSUED",
        "issued_at": now,
        "expires_at": now + timedelta(days=constants.GUEST_PASS_VALID_DAYS),
    })
    db.store.guest_passes[rec["id"]] = rec
    member["guest_passes_remaining"] -= 1
    models.touch(member)
    return success(models.serialize_guest_pass(rec), status=201)


@bp.route("/guest-passes/<pass_id>", methods=["GET"])
def get_guest_pass(pass_id):
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    rec = lookups.get_guest_pass(pass_id)
    require_owner(caller, rec["member_id"])
    return success(models.serialize_guest_pass(rec), status=200)


@bp.route("/guest-passes", methods=["GET"])
def list_guest_passes():
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    items = list(db.store.guest_passes.values())
    if caller.is_member:
        items = [g for g in items if g["member_id"] == caller.user_id]
    member_id = request.args.get("member_id")
    location_id = request.args.get("location_id")
    status = request.args.get("status")
    if member_id is not None:
        items = [g for g in items if g["member_id"] == member_id]
    if location_id is not None:
        items = [g for g in items if g["location_id"] == location_id]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    limit, offset = parse_pagination(request.args)
    page, pagination = paginate(items, limit, offset)
    return success([models.serialize_guest_pass(g) for g in page], status=200, pagination=pagination)


@bp.route("/guest-passes/<pass_id>/revoke", methods=["POST"])
def revoke_guest_pass(pass_id):
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    rec = lookups.get_guest_pass(pass_id)

    if rec["status"] != "ISSUED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Guest pass is not ISSUED")

    rec["status"] = "REVOKED"
    models.touch(rec)
    member = db.store.members.get(rec["member_id"])
    if member is not None:
        member["guest_passes_remaining"] += 1
        models.touch(member)
    return success(models.serialize_guest_pass(rec), status=200)
