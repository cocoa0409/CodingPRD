"""ServiceLine endpoints."""

from flask import Blueprint

from db import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_STALE_VERSION
from middleware import get_auth, require_roles, get_json_body
from response import success_object, paginate
from serializers import service_line_json, report_json
from services import new_common, touch
from util import is_int, is_num, iso_seconds, compute_release_deadline

bp = Blueprint("service_lines", __name__)


@bp.route("/service-lines", methods=["POST"])
def create_service_line():
    require_roles("SchedulingAdmin")
    body = get_json_body()
    # shape
    name = body.get("name")
    target = body.get("target_utilization_pct")
    rdh = body.get("release_deadline_hours", 72)
    if not isinstance(name, str) or not name:
        raise ApiError(ERR_INVALID_REQUEST, 400, "name is required and must be a string")
    if not is_num(target):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "target_utilization_pct is required and must be a number"
        )
    if not is_int(rdh):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "release_deadline_hours must be an integer"
        )
    rec = new_common()
    rec.update(
        {
            "name": name,
            "target_utilization_pct": target,
            "release_deadline_hours": rdh,
        }
    )
    db.service_lines[rec["id"]] = rec
    return success_object(service_line_json(rec), 201)


@bp.route("/service-lines", methods=["GET"])
def list_service_lines():
    get_auth()
    items = [service_line_json(s) for s in db.service_lines.values()]
    items.sort(key=lambda r: (r["created_at"],))
    return paginate(items)


@bp.route("/service-lines/<lineId>", methods=["GET"])
def get_service_line(lineId):
    get_auth()
    rec = db.service_lines.get(lineId)
    if rec is None:
        raise ApiError("ERR_SERVICE_LINE_NOT_FOUND", 404, "service line not found")
    return success_object(service_line_json(rec))


@bp.route("/service-lines/<lineId>", methods=["PATCH"])
def update_service_line(lineId):
    require_roles("SchedulingAdmin")
    rec = db.service_lines.get(lineId)
    if rec is None:
        raise ApiError("ERR_SERVICE_LINE_NOT_FOUND", 404, "service line not found")
    body = get_json_body()
    # shape: expected_service_line_version is required (OCC guard)
    expected = body.get("expected_service_line_version")
    if not is_int(expected):
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "expected_service_line_version is required and must be an integer",
        )
    target = body.get("target_utilization_pct", None)
    rdh = body.get("release_deadline_hours", None)
    if target is not None and not is_num(target):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "target_utilization_pct must be a number"
        )
    if rdh is not None and not is_int(rdh):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "release_deadline_hours must be an integer"
        )
    # OCC (after state preconditions, before business rules)
    if expected != rec["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            412,
            "expected_service_line_version does not match the current version",
        )
    if target is not None:
        rec["target_utilization_pct"] = target
    if rdh is not None:
        rec["release_deadline_hours"] = rdh
    touch(rec)
    # recompute release_deadline_at of DRAFT/ACTIVE blocks of the line
    for block in list(db.blocks.values()):
        if block["service_line_id"] == rec["id"] and block["status"] in (
            "DRAFT",
            "ACTIVE",
        ):
            block["release_deadline_at"] = iso_seconds(
                compute_release_deadline(
                    block["date"], block["start_minute"], rec["release_deadline_hours"]
                )
            )
            touch(block)
    return success_object(service_line_json(rec))


@bp.route("/service-lines/<lineId>/utilization-reports", methods=["GET"])
def list_line_reports(lineId):
    get_auth()
    line = db.service_lines.get(lineId)
    if line is None:
        raise ApiError("ERR_SERVICE_LINE_NOT_FOUND", 404, "service line not found")
    items = [
        report_json(r)
        for r in db.reports.values()
        if r["service_line_id"] == lineId
    ]
    items.sort(key=lambda r: (r["created_at"],))
    return paginate(items)
