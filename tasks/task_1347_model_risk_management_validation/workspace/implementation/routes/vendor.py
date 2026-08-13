"""Vendor transparency assessment endpoints: record, list."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import BUSINESS_ROLES, require_roles
from response import success, success_list
from routes.models import get_model_or_404
from serializers import assessment_json
from utils import add_months, new_id
from validate import get_body, pagination_params, v_int

bp = Blueprint("vendor", __name__)


@bp.post("/mrm/models/<model_id>/vendor-assessments")
def create_assessment(model_id):
    body = get_body()
    completeness_score = v_int(body, "completeness_score", minimum=0, maximum=100)
    valid_months = v_int(body, "valid_months", minimum=1)
    require_roles("ModelRiskOfficer")
    with store.lock:
        model = get_model_or_404(model_id)
        if model["status"] == "RETIRED":
            raise ApiError("ERR_MODEL_ALREADY_RETIRED", 409, "Model is RETIRED")
        if not model["is_vendor_model"]:
            raise ApiError(
                "ERR_NOT_A_VENDOR_MODEL",
                409,
                "Vendor transparency assessments exist only for vendor models",
            )
        now = store.now()
        assessment = {
            "id": new_id(),
            "model_id": model_id,
            "completeness_score": completeness_score,
            "valid_months": valid_months,
            "assessed_at": now,
            "valid_until": add_months(now, valid_months),
            "status": "CURRENT",
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": store.next_seq(),
        }
        store.assessments[assessment["id"]] = assessment
        return success(assessment_json(assessment), 201)


@bp.get("/mrm/models/<model_id>/vendor-assessments")
def list_assessments(model_id):
    require_roles(*BUSINESS_ROLES)
    limit, offset = pagination_params()
    f_status = request.args.get("status")
    with store.lock:
        get_model_or_404(model_id)
        items = [a for a in store.assessments.values() if a["model_id"] == model_id]
        items.sort(key=lambda a: (a["created_at"], a["_seq"]))
        if f_status is not None:
            items = [a for a in items if a["status"] == f_status]
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([assessment_json(a) for a in page], limit, offset, total)
