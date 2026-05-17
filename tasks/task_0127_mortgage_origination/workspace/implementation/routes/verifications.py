"""Income/Asset verification endpoints."""

from flask import Blueprint, g

from config import ROLE_LOAN_OFFICER
from middleware import require_role
from response import get_json_body, success
from services import loan_applications as la_svc, serializers, verifications as svc


verifications_bp = Blueprint("verifications", __name__)


# -------------- Income --------------
@verifications_bp.post("/loan-applications/<application_id>/income-verifications")
def income_create(application_id):
    require_role(ROLE_LOAN_OFFICER)
    application = la_svc.get_or_404(application_id)
    body = get_json_body()
    iv = svc.income_create(application, body)
    return success(serializers.income_verification(iv), status_code=201)


@verifications_bp.post(
    "/loan-applications/<application_id>/income-verifications/<iv_id>/verify"
)
def income_verify(application_id, iv_id):
    require_role(ROLE_LOAN_OFFICER)
    application = la_svc.get_or_404(application_id)
    iv = svc.income_get_or_404(application_id, iv_id)
    body = get_json_body()
    iv = svc.income_verify(application, iv, g.user_id, body)
    return success(serializers.income_verification(iv))


@verifications_bp.post(
    "/loan-applications/<application_id>/income-verifications/<iv_id>/reject"
)
def income_reject(application_id, iv_id):
    require_role(ROLE_LOAN_OFFICER)
    la_svc.get_or_404(application_id)
    iv = svc.income_get_or_404(application_id, iv_id)
    body = get_json_body()
    iv = svc.income_reject(iv, body)
    return success(serializers.income_verification(iv))


# -------------- Asset --------------
@verifications_bp.post("/loan-applications/<application_id>/asset-verifications")
def asset_create(application_id):
    require_role(ROLE_LOAN_OFFICER)
    application = la_svc.get_or_404(application_id)
    body = get_json_body()
    av = svc.asset_create(application, body)
    return success(serializers.asset_verification(av), status_code=201)


@verifications_bp.post(
    "/loan-applications/<application_id>/asset-verifications/<av_id>/verify"
)
def asset_verify(application_id, av_id):
    require_role(ROLE_LOAN_OFFICER)
    la_svc.get_or_404(application_id)
    av = svc.asset_get_or_404(application_id, av_id)
    body = get_json_body()
    av = svc.asset_verify(av, g.user_id, body)
    return success(serializers.asset_verification(av))


@verifications_bp.post(
    "/loan-applications/<application_id>/asset-verifications/<av_id>/reject"
)
def asset_reject(application_id, av_id):
    require_role(ROLE_LOAN_OFFICER)
    la_svc.get_or_404(application_id)
    av = svc.asset_get_or_404(application_id, av_id)
    body = get_json_body()
    av = svc.asset_reject(av, body)
    return success(serializers.asset_verification(av))
