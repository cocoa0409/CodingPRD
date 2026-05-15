"""Family endpoints."""
from flask import Blueprint, jsonify

from ..auth import require_auth
from ..errors import APIError
from ..responses import success_response
from ..services.lookups import fk_district, get_family_or_404
from ..store import get_lock, get_store, stamp_create
from ..validators import get_json_body, require_number, require_string


bp = Blueprint("families", __name__, url_prefix="/enrollment/families")


def _serialize(f: dict) -> dict:
    return {
        "id": f["id"],
        "residency_district_id": f["residency_district_id"],
        "poverty_index_score": f["poverty_index_score"],
        "head_household_application_id": f.get("head_household_application_id"),
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


@bp.route("", methods=["POST"])
@require_auth("FamilyUser", "SystemOperator")
def create_family():
    body = get_json_body()
    residency_district_id = require_string(body, "residency_district_id")
    poverty_index_score = require_number(body, "poverty_index_score",
                                         minimum=0.00, maximum=1.00, max_decimals=2)
    with get_lock():
        fk_district(residency_district_id)
        record = {
            "residency_district_id": residency_district_id,
            "poverty_index_score": poverty_index_score,
            "head_household_application_id": None,
        }
        stamp_create(record)
        get_store().families[record["id"]] = record
        resp, status = success_response(_serialize(record), status=201, response_type="object")
    return jsonify(resp), status


@bp.route("/<family_id>", methods=["GET"])
@require_auth("FamilyUser", "DistrictAdmin", "SystemOperator")
def get_family(family_id):
    rec = get_family_or_404(family_id)
    resp, status = success_response(_serialize(rec), status=200, response_type="object")
    return jsonify(resp), status
