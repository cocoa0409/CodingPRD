"""Surgeon endpoints."""

from flask import Blueprint

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_SERVICE_LINE_NOT_FOUND,
    ERR_SURGEON_NOT_FOUND,
)
from middleware import get_auth, require_roles, get_json_body
from response import success_object, paginate
from serializers import surgeon_json
from services import new_common

bp = Blueprint("surgeons", __name__)


@bp.route("/surgeons", methods=["POST"])
def create_surgeon():
    require_roles("SchedulingAdmin")
    body = get_json_body()
    service_line_id = body.get("service_line_id")
    full_name = body.get("full_name")
    # body FK existence
    if isinstance(service_line_id, str) and service_line_id not in db.service_lines:
        raise ApiError(ERR_SERVICE_LINE_NOT_FOUND, 404, "service line not found")
    # shape
    if not isinstance(service_line_id, str) or not service_line_id:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "service_line_id is required and must be a string"
        )
    if not isinstance(full_name, str) or not full_name:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "full_name is required and must be a string"
        )
    rec = new_common()
    rec.update(
        {
            "service_line_id": service_line_id,
            "full_name": full_name,
            "duration_bias_factor": 1.0,
            "completed_cases_count": 0,
            "on_time_rate_pct": 0.0,
        }
    )
    db.surgeons[rec["id"]] = rec
    return success_object(surgeon_json(rec), 201)


@bp.route("/surgeons", methods=["GET"])
def list_surgeons():
    get_auth()
    from flask import request as req

    items = list(db.surgeons.values())
    sl = req.args.get("service_line_id")
    if sl is not None:
        items = [s for s in items if s["service_line_id"] == sl]
    out = [surgeon_json(s) for s in items]
    out.sort(key=lambda r: (r["created_at"],))
    return paginate(out)


@bp.route("/surgeons/<surgeonId>", methods=["GET"])
def get_surgeon(surgeonId):
    get_auth()
    rec = db.surgeons.get(surgeonId)
    if rec is None:
        raise ApiError(ERR_SURGEON_NOT_FOUND, 404, "surgeon not found")
    return success_object(surgeon_json(rec))
