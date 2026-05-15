"""Routes for /housekeepers."""

from flask import Blueprint, request, g

from db import DB, LOCK
from errors import (
    raise_error,
    ERR_HOUSEKEEPER_NOT_FOUND,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_REQUEST,
)
from middleware import auth_required
from response import success_response, list_response
from services.common import (
    bump,
    require_body_dict,
    require_enum,
    require_field,
    stamp_create,
)
from services.pagination import parse_pagination, paginate
from services.serializers import serialize_housekeeper


bp = Blueprint("housekeepers", __name__)

SHIFT_STATUSES = {"ON_SHIFT", "OFF_SHIFT"}


def get_housekeeper_or_404(hk_id):
    hk = DB["housekeepers"].get(hk_id)
    if hk is None:
        raise_error(ERR_HOUSEKEEPER_NOT_FOUND, "Housekeeper not found")
    return hk


@bp.route("/housekeepers", methods=["POST"])
@auth_required(["Supervisor"])
def create_housekeeper():
    body = require_body_dict(request.get_json(silent=True))
    employee_code = require_field(body, "employee_code", str)
    display_name = require_field(body, "display_name", str)
    assigned_zone = require_field(body, "assigned_zone", str)

    if not employee_code:
        raise_error(ERR_INVALID_REQUEST, "employee_code must be non-empty")

    with LOCK:
        for h in DB["housekeepers"].values():
            if h["employee_code"] == employee_code:
                raise_error(ERR_INVALID_REQUEST,
                            "employee_code must be unique")
        hk = {
            "employee_code": employee_code,
            "display_name": display_name,
            "assigned_zone": assigned_zone,
            "shift_status": "OFF_SHIFT",
        }
        stamp_create(hk)
        DB["housekeepers"][hk["id"]] = hk
    return success_response(serialize_housekeeper(hk), http_status=201)


@bp.route("/housekeepers", methods=["GET"])
@auth_required(["Supervisor", "FrontDesk", "Housekeeper", "Engineer"])
def list_housekeepers():
    limit, offset = parse_pagination()
    zone_filter = request.args.get("zone")
    shift_filter = request.args.get("shift_status")
    items = list(DB["housekeepers"].values())
    if zone_filter:
        items = [h for h in items if h["assigned_zone"] == zone_filter]
    if shift_filter:
        items = [h for h in items if h.get("shift_status") == shift_filter]
    items.sort(key=lambda h: h["created_at"])
    page, total = paginate(items, limit, offset)
    return list_response(
        [serialize_housekeeper(h) for h in page], total, limit, offset
    )


@bp.route("/housekeepers/<hk_id>", methods=["GET"])
@auth_required(["Supervisor", "FrontDesk", "Housekeeper", "Engineer"])
def get_housekeeper(hk_id):
    hk = get_housekeeper_or_404(hk_id)
    return success_response(serialize_housekeeper(hk))


@bp.route("/housekeepers/<hk_id>/shift", methods=["POST"])
@auth_required(["Supervisor", "Housekeeper"])
def toggle_shift(hk_id):
    body = require_body_dict(request.get_json(silent=True))
    new_status = require_enum(body, "shift_status", SHIFT_STATUSES)

    with LOCK:
        hk = get_housekeeper_or_404(hk_id)
        # Housekeeper may only self-toggle
        if g.user_role == "Housekeeper" and g.user_id != hk["id"]:
            raise_error(ERR_INSUFFICIENT_PERMISSIONS,
                        "Housekeepers may only toggle their own shift")
        hk["shift_status"] = new_status
        bump(hk)
    return success_response(serialize_housekeeper(hk))
