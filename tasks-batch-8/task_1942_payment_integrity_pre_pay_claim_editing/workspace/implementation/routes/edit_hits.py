"""EditHit read endpoints."""

from flask import Blueprint, request

import db
from errors import raise_err
from middleware import pagination_params, require_auth
from response import success_list, success_object
from serializers import serialize

bp = Blueprint("edit_hits", __name__)
PREFIX = "/payment-integrity"

HIT_STATUSES = {"FIRED", "CONFIRMED", "OVERRIDDEN", "RELEASED_FALSE_POSITIVE", "SUPERSEDED"}


@bp.route(PREFIX + "/edit-hits", methods=["GET"])
def list_edit_hits():
    require_auth()
    limit, offset = pagination_params()
    claim_line_id = request.args.get("claim_line_id")
    edit_version_id = request.args.get("edit_version_id")
    vendor_edit_id = request.args.get("vendor_edit_id")
    status = request.args.get("status")
    rows = db.all_records("edit_hits")
    if claim_line_id is not None:
        rows = [r for r in rows if r["claim_line_id"] == claim_line_id]
    if edit_version_id is not None:
        rows = [r for r in rows if r["edit_version_id"] == edit_version_id]
    if vendor_edit_id is not None:
        rows = [r for r in rows if r.get("vendor_edit_id") == vendor_edit_id]
    if status is not None:
        if status not in HIT_STATUSES:
            raise_err("ERR_INVALID_ENUM", "status filter carries undeclared member")
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    return success_list([serialize(r) for r in rows[offset : offset + limit]], limit, offset, total)


@bp.route(PREFIX + "/edit-hits/<hid>", methods=["GET"])
def get_edit_hit(hid):
    require_auth()
    hit = db.get("edit_hits", hid)
    if hit is None:
        raise_err("ERR_EDIT_HIT_NOT_FOUND", "Edit hit not found")
    return success_object(serialize(hit))
