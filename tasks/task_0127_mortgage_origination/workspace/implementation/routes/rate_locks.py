"""RateLock endpoints."""

from flask import Blueprint

from config import (
    ROLE_ADMIN,
    ROLE_BORROWER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_LOAN_OFFICER,
)
from errors import ERR_RESOURCE_NOT_FOUND, raise_error
from middleware import require_role
from response import get_json_body, success
from services import loan_applications as la_svc, rate_locks as svc, serializers


rate_locks_bp = Blueprint("rate_locks", __name__)


@rate_locks_bp.post("/loan-applications/<application_id>/rate-lock")
def rate_lock_create(application_id):
    require_role(ROLE_LOAN_OFFICER)
    application = la_svc.get_or_404(application_id)
    body = get_json_body()
    rl = svc.create(application, body)
    return success(serializers.rate_lock(rl), status_code=201)


@rate_locks_bp.post("/loan-applications/<application_id>/rate-lock/extend")
def rate_lock_extend(application_id):
    require_role(ROLE_LOAN_OFFICER)
    application = la_svc.get_or_404(application_id)
    body = get_json_body()
    rl = svc.extend(application, body)
    return success(serializers.rate_lock(rl))


@rate_locks_bp.post("/loan-applications/<application_id>/rate-lock/cancel")
def rate_lock_cancel(application_id):
    require_role(ROLE_LOAN_OFFICER)
    application = la_svc.get_or_404(application_id)
    body = get_json_body()
    rl = svc.cancel(application, body)
    return success(serializers.rate_lock(rl))


@rate_locks_bp.get("/loan-applications/<application_id>/rate-lock")
def rate_lock_get(application_id):
    require_role(ROLE_LOAN_OFFICER, ROLE_COMPLIANCE_OFFICER, ROLE_ADMIN, ROLE_BORROWER)
    la_svc.get_or_404(application_id)
    rl = svc.get_for_app(application_id)
    if rl is None:
        raise_error(ERR_RESOURCE_NOT_FOUND, "No rate lock for this application.")
    return success(serializers.rate_lock(rl))
