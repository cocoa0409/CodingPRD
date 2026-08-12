"""ProductionBaseline endpoints."""

import math
from flask import Blueprint, request

import db
from db import DB
from errors import ApiError
from helpers import (
    D, to_float, req_body, require_fields, req_int, req_number,
    pagination_params, page_slice, get_or_404, touch,
)
from middleware import get_auth, require_role, check_grower_ownership
from response import success_object, success_list
from serializers import ser_baseline
from services import RISK_TREND_FACTOR


bp = Blueprint("baselines", __name__)


@bp.route("/advisory/production-baselines", methods=["POST"])
def create_baseline():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    body = req_body()
    require_fields(body, ["operation_id", "planted_acres", "aph_yield_bushels", "trend_yield_bushels", "expected_operation_version"])
    operation_id = body["operation_id"]
    if not isinstance(operation_id, str):
        raise ApiError("ERR_VALIDATION", "operation_id must be a string", 400)
    planted_acres = req_int(body, "planted_acres", positive=True)
    aph_yield = req_number(body, "aph_yield_bushels", positive=True)
    trend_yield = req_number(body, "trend_yield_bushels", positive=True)

    # Field-level schema first
    eov = body.get("expected_operation_version")
    if isinstance(eov, bool) or not isinstance(eov, int):
        raise ApiError("ERR_VALIDATION", "expected_operation_version must be an integer", 400)

    op = DB.operations.get(operation_id)
    if op is None:
        raise ApiError("ERR_NOT_FOUND", f"GrowerOperation not found: {operation_id}", 404)

    # OCC check
    if eov != op["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_operation_version does not match the operation's current version", 412)

    # Compute variants
    aph_variant = int((D(planted_acres) * aph_yield).to_integral_value(rounding="ROUND_FLOOR"))
    trend_variant = int(
        (D(planted_acres) * trend_yield * RISK_TREND_FACTOR[op["risk_profile"]]).to_integral_value(
            rounding="ROUND_FLOOR"
        )
    )
    expected = aph_variant if op["yield_method"] == "APH" else trend_variant

    # Supersede existing non-SUPERSEDED baselines for this operation
    for b in DB.baselines.values():
        if b["operation_id"] == operation_id and b["status"] != "SUPERSEDED":
            b["status"] = "SUPERSEDED"
            touch(b)

    bid = db.new_id()
    now = db.now_iso()
    baseline = {
        "id": bid,
        "operation_id": operation_id,
        "planted_acres": planted_acres,
        "aph_yield_bushels": aph_yield,
        "trend_yield_bushels": trend_yield,
        "expected_bushels_aph": aph_variant,
        "expected_bushels_trend": trend_variant,
        "expected_bushels": expected,
        "status": "PROVISIONAL",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.baselines[bid] = baseline
    touch(op)
    return success_object(ser_baseline(baseline), status=201)


@bp.route("/advisory/production-baselines/<baselineId>", methods=["GET"])
def get_baseline(baselineId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower", "ComplianceOfficer"])
    b = get_or_404(DB.baselines, baselineId, "ProductionBaseline")
    check_grower_ownership(user_id, role, b["operation_id"])
    return success_object(ser_baseline(b))


@bp.route("/advisory/production-baselines", methods=["GET"])
def list_baselines():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower", "ComplianceOfficer"])
    limit, offset = pagination_params()
    operation_id = request.args.get("operation_id")
    status = request.args.get("status")
    items = list(DB.baselines.values())
    if role == "Grower":
        items = [b for b in items if b["operation_id"] == user_id]
    if operation_id is not None:
        items = [b for b in items if b["operation_id"] == operation_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda b: b["created_at"])
    slice_, total = page_slice(items, limit, offset)
    return success_list([ser_baseline(b) for b in slice_], limit, offset, total)


@bp.route("/advisory/production-baselines/<baselineId>/certify", methods=["POST"])
def certify_baseline(baselineId):
    user_id, role = get_auth()
    require_role(role, ["Grower"])
    b = get_or_404(DB.baselines, baselineId, "ProductionBaseline")
    check_grower_ownership(user_id, role, b["operation_id"])
    if b["status"] != "PROVISIONAL":
        raise ApiError("ERR_INVALID_STATE", f"Baseline in state {b['status']} cannot be certified", 409)
    # No other CERTIFIED baseline for same operation
    for other in DB.baselines.values():
        if other["operation_id"] == b["operation_id"] and other["id"] != b["id"] and other["status"] == "CERTIFIED":
            raise ApiError("ERR_INVALID_STATE", "Another CERTIFIED baseline exists for this operation", 409)
    b["status"] = "CERTIFIED"
    touch(b)
    return success_object(ser_baseline(b))
