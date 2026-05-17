"""Appraisal endpoints."""

from flask import Blueprint

from config import ROLE_LOAN_OFFICER
from middleware import require_role
from response import get_json_body, success
from services import appraisals as svc, loan_applications as la_svc, serializers


appraisals_bp = Blueprint("appraisals", __name__)


@appraisals_bp.post("/loan-applications/<application_id>/appraisal")
def appraisal_create(application_id):
    require_role(ROLE_LOAN_OFFICER)
    application = la_svc.get_or_404(application_id)
    body = get_json_body()
    a = svc.create(application, body)
    return success(serializers.appraisal(a), status_code=201)


@appraisals_bp.post("/loan-applications/<application_id>/appraisal/complete")
def appraisal_complete(application_id):
    require_role(ROLE_LOAN_OFFICER)
    application = la_svc.get_or_404(application_id)
    body = get_json_body()
    a = svc.complete(application, body)
    return success(serializers.appraisal(a))


@appraisals_bp.post("/loan-applications/<application_id>/appraisal/reject")
def appraisal_reject(application_id):
    require_role(ROLE_LOAN_OFFICER)
    application = la_svc.get_or_404(application_id)
    body = get_json_body()
    a = svc.reject(application, body)
    return success(serializers.appraisal(a))
