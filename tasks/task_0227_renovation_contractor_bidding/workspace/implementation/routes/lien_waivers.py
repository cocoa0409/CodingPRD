"""Lien waiver routes (file UNCONDITIONAL waiver, fetch, list)."""
from flask import Blueprint, request

import db
import errors
import response
from middleware import require_roles
from services import common, lookups

bp = Blueprint("lien_waivers", __name__)

WAIVER_TYPES = {"CONDITIONAL", "UNCONDITIONAL"}


@bp.route("/lien-waivers", methods=["POST"])
def create_waiver():
    user_id, role = require_roles("Contractor")
    body = common.get_body()
    project_id = common.as_str(common.require_field(body, "project_id"), "project_id")
    contractor_id = common.as_str(common.require_field(body, "contractor_id"), "contractor_id")
    draw_id = common.as_str(common.require_field(body, "draw_id"), "draw_id")
    waiver_type = common.as_enum(
        common.require_field(body, "waiver_type"), "waiver_type", WAIVER_TYPES)
    amount = common.as_int(common.require_field(body, "amount_cents"), "amount_cents")
    if amount < 0:
        raise errors.invalid_request("amount_cents must be >= 0.")
    # existence
    lookups.get_project(project_id)
    lookups.get_contractor(contractor_id)
    draw = lookups.get_draw(draw_id)
    # ownership: contractor files their own waivers
    if contractor_id != user_id:
        raise errors.not_owner("Contractor can only file waivers for themselves.")

    rec = {
        "project_id": project_id,
        "contractor_id": contractor_id,
        "draw_id": draw_id,
        "waiver_type": waiver_type,
        "amount_cents": amount,
        "status": "COLLECTED",
    }
    common.stamp_new(rec)
    db.lien_waivers[rec["id"]] = rec
    return response.success(common.public(rec), 201)


@bp.route("/lien-waivers/<rid>", methods=["GET"])
def get_waiver(rid):
    require_roles("Contractor", "Homeowner", "EscrowAgent", "PlatformAdmin")
    rec = lookups.get_lien_waiver(rid)
    return response.success(common.public(rec), 200)


@bp.route("/lien-waivers", methods=["GET"])
def list_waivers():
    require_roles("Contractor", "Homeowner", "EscrowAgent", "PlatformAdmin")
    items = list(db.lien_waivers.values())
    for field in ("project_id", "contractor_id", "draw_id", "waiver_type", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [w for w in items if w.get(field) == val]
    page, limit, offset, total = common.paginate(items)
    return response.success_list(page, limit, offset, total, 200)
