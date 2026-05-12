"""OverbookingPolicy routes."""
from flask import Blueprint, request

from db import overbooking_policies, room_types, stamp_create, stamp_update, lock
from errors import err
from middleware import require_auth
from response import success
from services.projections import project_overbooking_policy
from services.validation import require_dict, required_str, required_int, in_range, at_least
from services.pricing import compute_walkout_estimate
from clock import parse_date

bp = Blueprint("overbooking", __name__)


@bp.route("/hotel/overbooking-policies", methods=["POST"])
@require_auth(roles=["RevenueManager"])
def create_policy():
    body = require_dict(request.get_json(silent=True))
    room_type_id = required_str(body, "room_type_id")
    stay_date_raw = required_str(body, "stay_date")
    overbook_bp = required_int(body, "overbook_ratio_basis_points")
    in_range(overbook_bp, 0, 5000, "overbook_ratio_basis_points")
    p_no_show_bp = required_int(body, "estimated_no_show_probability_basis_points")
    in_range(p_no_show_bp, 0, 10000, "estimated_no_show_probability_basis_points")
    walkout_comp = required_int(body, "walkout_compensation_cents")
    at_least(walkout_comp, 0, "walkout_compensation_cents")
    try:
        sd = parse_date(stay_date_raw)
    except ValueError as e:
        raise err("ERR_INVALID_INPUT", str(e))

    with lock():
        rt = room_types.get(room_type_id)
        if rt is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "RoomType not found")

        # Cascade: any prior ACTIVE policy on (room_type_id, stay_date) -> SUPERSEDED
        for p in overbooking_policies.values():
            if (p.get("room_type_id") == room_type_id
                    and p.get("stay_date") == sd.isoformat()
                    and p.get("status") == "ACTIVE"):
                p["status"] = "SUPERSEDED"
                stamp_update(p)

        row = {
            "room_type_id": room_type_id,
            "stay_date": sd.isoformat(),
            "overbook_ratio_basis_points": overbook_bp,
            "estimated_no_show_probability_basis_points": p_no_show_bp,
            "walkout_compensation_cents": walkout_comp,
            "status": "ACTIVE",
        }
        stamp_create(row, common_fields=True)
        overbooking_policies[row["id"]] = row
    return success(project_overbooking_policy(row), 201)


@bp.route("/hotel/overbooking-policies/<rt_id>/<stay_date>/walkout-cost-estimate", methods=["GET"])
@require_auth(roles=["RevenueAnalyst", "RevenueManager"])
def walkout_estimate(rt_id, stay_date):
    # Path params: validate left-to-right
    rt = room_types.get(rt_id)
    if rt is None:
        raise err("ERR_NOT_FOUND", "RoomType not found")
    try:
        sd = parse_date(stay_date)
    except ValueError as e:
        raise err("ERR_INVALID_INPUT", str(e))
    result = compute_walkout_estimate(rt_id, sd.isoformat())
    if result is None:
        raise err("ERR_NOT_FOUND", "No active OverbookingPolicy for (room_type_id, stay_date)")
    return success(result)
