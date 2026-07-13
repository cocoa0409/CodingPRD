from flask import Blueprint, request

from db import db
from errors import ApiError
from helpers import (
    get_json_body, new_common_fields, paginate,
    parse_pagination, require_fields, require_enum, require_type,
    sorted_by_created, strip_internal,
)
from middleware import require_role
from response import success_array, success_object

bp = Blueprint("countermeasures", __name__)

COUNTERMEASURE_TYPES = {"VACCINE", "ANTIVIRAL", "ANTIBIOTIC_PEP"}
ALL_ROLES = ["PublicHealthAdmin", "LogisticsCoordinator", "MutualAidPartner", "ClinicalLead", "Volunteer"]


@bp.route("/countermeasures", methods=["POST"])
@require_role("PublicHealthAdmin")
def create_countermeasure():
    body = get_json_body()
    require_fields(body, ["name", "countermeasure_type", "doses_required", "unit_cost_cents", "reorder_point_quantity"])
    require_type(body["name"], str, "name")
    require_type(body["countermeasure_type"], str, "countermeasure_type")
    require_enum(body["countermeasure_type"], COUNTERMEASURE_TYPES, "countermeasure_type")
    require_type(body["doses_required"], int, "doses_required")
    if body["doses_required"] <= 0:
        raise ApiError("ERR_VALIDATION", "doses_required must be > 0.", 400)
    dose_interval_days = body.get("dose_interval_days", 0)
    require_type(dose_interval_days, int, "dose_interval_days")
    if dose_interval_days < 0:
        raise ApiError("ERR_VALIDATION", "dose_interval_days must be >= 0.", 400)
    require_type(body["unit_cost_cents"], int, "unit_cost_cents")
    if body["unit_cost_cents"] < 0:
        raise ApiError("ERR_VALIDATION", "unit_cost_cents must be >= 0.", 400)
    require_type(body["reorder_point_quantity"], int, "reorder_point_quantity")
    if body["reorder_point_quantity"] < 0:
        raise ApiError("ERR_VALIDATION", "reorder_point_quantity must be >= 0.", 400)

    row = new_common_fields()
    row.update({
        "name": body["name"],
        "countermeasure_type": body["countermeasure_type"],
        "doses_required": body["doses_required"],
        "dose_interval_days": dose_interval_days,
        "unit_cost_cents": body["unit_cost_cents"],
        "reorder_point_quantity": body["reorder_point_quantity"],
    })
    db.countermeasures[row["id"]] = row
    return success_object(strip_internal(row), 201)


@bp.route("/countermeasures", methods=["GET"])
@require_role(*ALL_ROLES)
def list_countermeasures():
    limit, offset = parse_pagination(request.args)
    countermeasure_type = request.args.get("countermeasure_type")
    rows = list(db.countermeasures.values())
    if countermeasure_type:
        rows = [r for r in rows if r["countermeasure_type"] == countermeasure_type]
    rows = sorted_by_created(rows)
    items, total = paginate(rows, limit, offset)
    return success_array(items, limit, offset, total)
