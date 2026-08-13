"""Bale and ClassingResult routes."""

from flask import Blueprint

from db import db, parse_dt, is_valid_datetime
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_BALE_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_NO_ACTIVE_GRADE_SCHEDULE,
)
from middleware import (
    get_context,
    require_role,
    grower_owns,
    parse_pagination,
    get_json_body,
    require_fields,
    require_number,
    require_int,
)
from response import success_object
from services.core import stamp_new, touch, sorted_entities, paginate
from services.calc import (
    find_covering_schedule,
    compute_quality_points,
    compute_adjustment_cents,
    recompute_draft_settlements,
)

bp = Blueprint("bales", __name__)


def bale_out(b):
    return {
        "id": b["id"],
        "module_id": b["module_id"],
        "bale_tag": b["bale_tag"],
        "net_weight_lbs": b["net_weight_lbs"],
        "classing_status": b["classing_status"],
        "custody_status": b["custody_status"],
        "active_grade_code": b["active_grade_code"],
        "quality_points": b["quality_points"],
        "adjustment_cents": b["adjustment_cents"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def classing_out(c):
    return {
        "id": c["id"],
        "bale_id": c["bale_id"],
        "grade_code": c["grade_code"],
        "micronaire": c["micronaire"],
        "strength_gpt": c["strength_gpt"],
        "staple_32nds": c["staple_32nds"],
        "classing_office": c["classing_office"],
        "result_date": c["result_date"],
        "status": c["status"],
        "quality_points": c["quality_points"],
        "adjustment_cents": c["adjustment_cents"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def _bale_grower_season(bale):
    module = db.modules.get(bale["module_id"])
    if module is None:
        return None, None
    return module["grower_id"], module["season"]


@bp.route("/gin-ops/bales/<bid>", methods=["GET"])
def get_bale(bid):
    user_id, role = get_context()
    b = db.bales.get(bid)
    if b is None:
        err_id, status = ERR_BALE_NOT_FOUND
        raise ApiError(err_id, "Bale not found", status)
    gid, _ = _bale_grower_season(b)
    grower_owns(user_id, role, gid)
    return success_object(bale_out(b))


@bp.route("/gin-ops/bales/<bid>/classing-results", methods=["POST"])
def create_classing_result(bid):
    user_id, role = get_context()
    require_role(role, {"ClassingClerk"})
    bale = db.bales.get(bid)
    if bale is None:
        err_id, status = ERR_BALE_NOT_FOUND
        raise ApiError(err_id, "Bale not found", status)
    body = get_json_body()
    require_fields(body, [
        "grade_code", "micronaire", "strength_gpt", "staple_32nds",
        "classing_office", "result_date", "expected_bale_version",
    ])
    grade_code = body["grade_code"]
    if not isinstance(grade_code, str) or not grade_code:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "grade_code must be a non-empty string", status)
    micronaire = require_number(body, "micronaire")
    strength = require_number(body, "strength_gpt")
    staple = require_int(body, "staple_32nds")
    office = body["classing_office"]
    if not isinstance(office, str) or not office:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "classing_office must be a non-empty string", status)
    rd_raw = body["result_date"]
    if not is_valid_datetime(rd_raw):
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "result_date must be a valid datetime", status)
    result_date = parse_dt(rd_raw)
    expected = body["expected_bale_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "expected_bale_version must be an integer", status)
    # OCC
    if expected != bale["version"]:
        err_id, status = ERR_STALE_VERSION
        raise ApiError(err_id, "expected_bale_version does not match current version", status)
    # Covering schedule
    schedule = find_covering_schedule(grade_code, result_date)
    if schedule is None:
        err_id, status = ERR_NO_ACTIVE_GRADE_SCHEDULE
        raise ApiError(err_id, "No active grade schedule covers result_date", status)

    quality_points = compute_quality_points(schedule["premium_discount_points"], micronaire, strength)
    adjustment = compute_adjustment_cents(bale["net_weight_lbs"], quality_points)

    # Supersede prior ACTIVE result
    for c in db.classing_results.values():
        if c["bale_id"] == bid and c["status"] == "ACTIVE":
            c["status"] = "SUPERSEDED"
            touch(c)

    result = stamp_new({
        "bale_id": bid,
        "grade_code": grade_code,
        "micronaire": micronaire,
        "strength_gpt": strength,
        "staple_32nds": staple,
        "classing_office": office,
        "result_date": result_date.strftime("%Y-%m-%dT00:00:00Z"),
        "status": "ACTIVE",
        "quality_points": quality_points,
        "adjustment_cents": adjustment,
    })
    db.classing_results[result["id"]] = result

    bale["active_grade_code"] = grade_code
    bale["quality_points"] = quality_points
    bale["adjustment_cents"] = adjustment
    bale["classing_status"] = "CLASSED"
    touch(bale)

    gid, season = _bale_grower_season(bale)
    if gid is not None:
        recompute_draft_settlements(gid, season)

    return success_object(classing_out(result), 201)


@bp.route("/gin-ops/bales/<bid>/classing-results", methods=["GET"])
def list_classing_results(bid):
    user_id, role = get_context()
    bale = db.bales.get(bid)
    if bale is None:
        err_id, status = ERR_BALE_NOT_FOUND
        raise ApiError(err_id, "Bale not found", status)
    gid, _ = _bale_grower_season(bale)
    grower_owns(user_id, role, gid)
    limit, offset = parse_pagination()
    items = [c for c in db.classing_results.values() if c["bale_id"] == bid]
    items = sorted_entities(items)
    return paginate([classing_out(c) for c in items], limit, offset)
