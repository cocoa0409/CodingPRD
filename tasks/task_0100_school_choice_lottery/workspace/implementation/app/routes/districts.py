"""District endpoints."""
from flask import Blueprint, jsonify

from ..auth import require_auth
from ..errors import APIError
from ..occ import check_version
from ..responses import list_response, success_response
from ..services.lookups import get_district_or_404
from ..store import get_lock, get_store, stamp_create, stamp_update
from ..validators import (get_json_body, optional_field, paginate,
                          parse_pagination, require_bool, require_number,
                          require_string)


bp = Blueprint("districts", __name__, url_prefix="/enrollment/districts")


def _serialize(d: dict) -> dict:
    return {
        "id": d["id"],
        "name": d["name"],
        "state_code": d["state_code"],
        "accepts_inter_district_transfers": d["accepts_inter_district_transfers"],
        "poverty_index_threshold": d["poverty_index_threshold"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


@bp.route("", methods=["POST"])
@require_auth("SystemOperator")
def create_district():
    body = get_json_body()
    name = require_string(body, "name", min_len=1, max_len=120)
    state_code = require_string(body, "state_code", pattern=r"^[A-Z]{2}$")

    accepts = optional_field(body, "accepts_inter_district_transfers", False)
    if not isinstance(accepts, bool):
        raise APIError("ERR_VALIDATION", "'accepts_inter_district_transfers' must be a boolean")

    threshold = optional_field(body, "poverty_index_threshold", 0.50)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise APIError("ERR_VALIDATION", "'poverty_index_threshold' must be a number")
    # range + decimals
    body_thr = dict(body)
    if "poverty_index_threshold" not in body_thr:
        body_thr["poverty_index_threshold"] = threshold
    threshold = require_number(body_thr, "poverty_index_threshold",
                               minimum=0.00, maximum=1.00, max_decimals=2)

    with get_lock():
        # Uniqueness on name
        for existing in get_store().districts.values():
            if existing["name"] == name:
                raise APIError("ERR_VALIDATION", "district name must be unique")
        record = {
            "name": name,
            "state_code": state_code,
            "accepts_inter_district_transfers": accepts,
            "poverty_index_threshold": threshold,
        }
        stamp_create(record)
        get_store().districts[record["id"]] = record
        resp, status = success_response(_serialize(record), status=201, response_type="object")
    return jsonify(resp), status


@bp.route("", methods=["GET"])
@require_auth("SystemOperator", "DistrictAdmin", "FamilyUser")
def list_districts():
    limit, offset = parse_pagination()
    items = sorted(get_store().districts.values(), key=lambda d: (d["created_at"], d["id"]))
    page, total = paginate(items, limit, offset)
    resp, status = list_response([_serialize(x) for x in page], total, limit, offset)
    return jsonify(resp), status


@bp.route("/<district_id>", methods=["GET"])
@require_auth("SystemOperator", "DistrictAdmin", "FamilyUser")
def get_district(district_id):
    rec = get_district_or_404(district_id)
    resp, status = success_response(_serialize(rec), status=200, response_type="object")
    return jsonify(resp), status


@bp.route("/<district_id>", methods=["PATCH"])
@require_auth("SystemOperator")
def patch_district(district_id):
    body = get_json_body()
    with get_lock():
        rec = get_district_or_404(district_id)
        check_version(rec, body)
        if "accepts_inter_district_transfers" in body and body["accepts_inter_district_transfers"] is not None:
            v = body["accepts_inter_district_transfers"]
            if not isinstance(v, bool):
                raise APIError("ERR_VALIDATION", "'accepts_inter_district_transfers' must be a boolean")
            rec["accepts_inter_district_transfers"] = v
        if "poverty_index_threshold" in body and body["poverty_index_threshold"] is not None:
            thr = require_number(body, "poverty_index_threshold",
                                 minimum=0.00, maximum=1.00, max_decimals=2)
            rec["poverty_index_threshold"] = thr
        stamp_update(rec)
        resp, status = success_response(_serialize(rec), status=200, response_type="object")
    return jsonify(resp), status
