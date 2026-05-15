"""School endpoints."""
from flask import Blueprint, g, jsonify

from ..auth import require_auth
from ..errors import APIError
from ..responses import list_response, success_response
from ..services.lookups import fk_district, get_school_or_404
from ..store import get_lock, get_store, stamp_create
from ..validators import (get_json_body, paginate, parse_pagination,
                          require_field, require_string)


bp = Blueprint("schools", __name__, url_prefix="/enrollment/schools")

VALID_TYPES = {"NEIGHBORHOOD", "MAGNET", "CHARTER"}


def _serialize(s: dict) -> dict:
    return {
        "id": s["id"],
        "district_id": s["district_id"],
        "name": s["name"],
        "school_type": s["school_type"],
        "grade_levels_offered": list(s["grade_levels_offered"]),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def _validate_grade_levels(value) -> list:
    if not isinstance(value, list) or not value:
        raise APIError("ERR_VALIDATION", "'grade_levels_offered' must be a non-empty array")
    out = []
    for v in value:
        if isinstance(v, bool) or not isinstance(v, int):
            raise APIError("ERR_VALIDATION", "'grade_levels_offered' must contain integers")
        if v < 0 or v > 12:
            raise APIError("ERR_VALIDATION", "grade levels must be in [0, 12]")
        out.append(v)
    if sorted(out) != out:
        raise APIError("ERR_VALIDATION", "'grade_levels_offered' must be sorted ascending")
    if len(set(out)) != len(out):
        raise APIError("ERR_VALIDATION", "'grade_levels_offered' must not contain duplicates")
    return out


@bp.route("", methods=["POST"])
@require_auth("DistrictAdmin")
def create_school():
    body = get_json_body()
    district_id = require_string(body, "district_id")
    name = require_string(body, "name", min_len=1, max_len=200)
    school_type = require_string(body, "school_type")
    if school_type not in VALID_TYPES:
        raise APIError("ERR_VALIDATION", f"school_type must be one of {sorted(VALID_TYPES)}")
    grade_levels = _validate_grade_levels(require_field(body, "grade_levels_offered"))

    with get_lock():
        fk_district(district_id)
        # DistrictAdmin must own the district
        if g.user_id != district_id:
            raise APIError("ERR_FORBIDDEN", "DistrictAdmin may only create schools in their own district")
        # Unique school name within district
        for s in get_store().schools.values():
            if s["district_id"] == district_id and s["name"] == name:
                raise APIError("ERR_VALIDATION", "school name must be unique within district")
        record = {
            "district_id": district_id,
            "name": name,
            "school_type": school_type,
            "grade_levels_offered": grade_levels,
        }
        stamp_create(record)
        get_store().schools[record["id"]] = record
        resp, status = success_response(_serialize(record), status=201, response_type="object")
    return jsonify(resp), status


@bp.route("", methods=["GET"])
@require_auth("SystemOperator", "DistrictAdmin", "FamilyUser")
def list_schools():
    limit, offset = parse_pagination()
    district_id = None
    school_type = None
    from flask import request
    if "district_id" in request.args:
        district_id = request.args.get("district_id")
    if "school_type" in request.args:
        school_type = request.args.get("school_type")
        if school_type not in VALID_TYPES:
            raise APIError("ERR_VALIDATION", "invalid school_type filter")
    items = [s for s in get_store().schools.values()
             if (district_id is None or s["district_id"] == district_id)
             and (school_type is None or s["school_type"] == school_type)]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    page, total = paginate(items, limit, offset)
    resp, status = list_response([_serialize(x) for x in page], total, limit, offset)
    return jsonify(resp), status


@bp.route("/<school_id>", methods=["GET"])
@require_auth("SystemOperator", "DistrictAdmin", "FamilyUser")
def get_school(school_id):
    rec = get_school_or_404(school_id)
    resp, status = success_response(_serialize(rec), status=200, response_type="object")
    return jsonify(resp), status
