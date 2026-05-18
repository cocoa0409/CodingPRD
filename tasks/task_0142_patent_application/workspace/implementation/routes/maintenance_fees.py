"""Maintenance Fee endpoints (SCAFFOLD §1.5).

GET    /maintenance-fees/{id}           -> Applicant, Examiner, USPTOAdmin
POST   /maintenance-fees/{id}/pay       -> Applicant
"""

from flask import Blueprint

from config import APP_STATUS_GRANTED, APP_TYPE_UTILITY, ROLE_APPLICANT, ROLE_EXAMINER, ROLE_USPTO_ADMIN
from db import store
from errors import make_error
from middleware import require_auth
from response import success
from services.patent_engine import _check_ownership_application, pay_maintenance_fee
from services.serializers import serialize_maintenance_fee


maintenance_fees_bp = Blueprint("maintenance_fees", __name__)


@maintenance_fees_bp.get("/maintenance-fees/<mf_id>")
@require_auth(allowed_roles=[ROLE_APPLICANT, ROLE_EXAMINER, ROLE_USPTO_ADMIN])
def get_maintenance_fee_route(mf_id: str):
    mf = store.maintenance_fees.get(mf_id)
    if mf is None:
        raise make_error("ERR_NOT_FOUND", f"MaintenanceFee {mf_id} not found.")
    application = store.applications.get(mf["application_id"])
    if application is not None:
        _check_ownership_application(application)
    return success(serialize_maintenance_fee(mf))


@maintenance_fees_bp.post("/maintenance-fees/<mf_id>/pay")
@require_auth(allowed_roles=[ROLE_APPLICANT])
def pay_maintenance_fee_route(mf_id: str):
    with store.lock:
        mf = pay_maintenance_fee(mf_id)
    return success(serialize_maintenance_fee(mf))
