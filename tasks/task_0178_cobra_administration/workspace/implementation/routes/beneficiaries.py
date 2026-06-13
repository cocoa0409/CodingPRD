"""Beneficiary endpoints + HIPAA certificate listing by beneficiary."""
from flask import Blueprint, request

from db import store
from middleware import require_role
from models import _common, serialize, BENEFICIARY_FIELDS, CERTIFICATE_FIELDS
from response import object_response, array_response
from services.lookup import (
    get_or_404, require_body, require_string, require_enum, require_datetime,
    paginate, sorted_by_creation,
)

bp = Blueprint("beneficiaries", __name__)


@bp.post("/beneficiaries")
@require_role({"PlanAdministrator", "PlanSponsor"})
def create_beneficiary():
    body = require_body()
    # Existence (FK) before body shape: validate plan_id reference exists.
    plan_id = body.get("plan_id")
    if plan_id is None:
        from errors import ApiError
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: plan_id")
    get_or_404(store.plans, plan_id)

    full_name = require_string(body, "full_name")
    relationship = require_enum(body, "relationship", {"EMPLOYEE", "SPOUSE", "DEPENDENT"})
    original_start = require_datetime(body, "original_coverage_start")

    ben = {
        "plan_id": plan_id,
        "full_name": full_name,
        "relationship": relationship,
        "original_coverage_start": original_start,
        "status": "ACTIVE_EMPLOYEE_COVERAGE",
    }
    _common(ben)
    store.beneficiaries[ben["id"]] = ben
    return object_response(serialize(ben, BENEFICIARY_FIELDS), status=201)


@bp.get("/beneficiaries/<bid>")
@require_role({"PlanAdministrator", "PlanSponsor", "BillingAgent", "QualifiedBeneficiary"})
def get_beneficiary(bid):
    ben = get_or_404(store.beneficiaries, bid)
    return object_response(serialize(ben, BENEFICIARY_FIELDS))


@bp.get("/beneficiaries/<bid>/certificates")
@require_role({"PlanAdministrator", "BillingAgent", "QualifiedBeneficiary"})
def list_beneficiary_certificates(bid):
    get_or_404(store.beneficiaries, bid)
    items = [c for c in store.certificates.values() if c["beneficiary_id"] == bid]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(c, CERTIFICATE_FIELDS) for c in page],
                          limit, offset, total)
