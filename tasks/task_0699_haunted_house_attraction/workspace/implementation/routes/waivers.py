"""Waiver endpoints (PRD §3.3)."""
from flask import Blueprint, request

import db
import errors
import response
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination, require_owner
from services import lookup
from services.common import require_int, touch, base_record, sort_and_paginate
from services.serialize import serialize_waiver, waiver_effective_status

bp = Blueprint("waivers", __name__)


@bp.route("/guests/<guest_id>/waivers", methods=["POST"])
def sign_waiver(guest_id):
    user_id, role = get_identity()
    require_role(role, {"BoxOffice", "Guest"})
    guest = lookup.guest(guest_id)
    # A guest may act only on their own resources.
    require_owner(role, user_id, guest["id"])
    body = get_json_body()
    max_scare_level = require_int(body, "max_scare_level", minimum=1, maximum=5)

    signed_at = db.now()
    expires_at = db.add_days(signed_at, db.WAIVER_VALID_DAYS)
    waiver = base_record()
    waiver.update({
        "guest_id": guest["id"],
        "max_scare_level": max_scare_level,
        "signed_at": db.iso(signed_at),
        "expires_at": db.iso(expires_at),
        "status": "SIGNED",
    })
    db.waivers[waiver["id"]] = waiver
    return response.success(serialize_waiver(waiver), 201)


@bp.route("/waivers/<waiver_id>", methods=["GET"])
def get_waiver(waiver_id):
    user_id, role = get_identity()
    require_role(role, {"OpsManager", "BoxOffice", "Guest"})
    waiver = lookup.waiver(waiver_id)
    require_owner(role, user_id, waiver["guest_id"])
    return response.success(serialize_waiver(waiver), 200)


@bp.route("/waivers", methods=["GET"])
def list_waivers():
    user_id, role = get_identity()
    require_role(role, {"OpsManager", "BoxOffice", "Guest"})
    limit, offset = parse_pagination()
    guest_id = request.args.get("guest_id")
    records = list(db.waivers.values())
    if guest_id is not None:
        records = [w for w in records if w["guest_id"] == guest_id]
    # A Guest may only list their own resources.
    if role == "Guest":
        records = [w for w in records if w["guest_id"] == user_id]
    page, total = sort_and_paginate(records, limit, offset)
    return response.success_list(
        [serialize_waiver(w) for w in page], limit, offset, total, 200
    )


@bp.route("/waivers/<waiver_id>/revoke", methods=["POST"])
def revoke_waiver(waiver_id):
    user_id, role = get_identity()
    require_role(role, {"Guest", "OpsManager"})
    waiver = lookup.waiver(waiver_id)
    require_owner(role, user_id, waiver["guest_id"])
    body = get_json_body()

    # Revoking moves a still-SIGNED waiver to REVOKED. The stored status field is
    # only ever SIGNED or REVOKED; EXPIRED is derived. A waiver that is not
    # currently effectively SIGNED cannot be revoked.
    if waiver_effective_status(waiver) != "SIGNED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a SIGNED waiver can be revoked.")

    # OCC on the waiver (PRD §2.10).
    expected = require_int(body, "expected_waiver_version")
    if expected != waiver["version"]:
        raise ApiError(errors.ERR_STALE_WAIVER_VERSION, 412,
                       "expected_waiver_version does not match the waiver version.")

    waiver["status"] = "REVOKED"
    touch(waiver)
    return response.success(serialize_waiver(waiver), 200)
