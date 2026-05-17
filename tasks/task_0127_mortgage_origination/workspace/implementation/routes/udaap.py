"""UDAAPReview endpoints."""

from flask import Blueprint, g

from config import ROLE_ADMIN, ROLE_COMPLIANCE_OFFICER
from middleware import require_role
from response import get_json_body, success, success_list
from services import loan_applications as la_svc, serializers, udaap as svc


udaap_bp = Blueprint("udaap", __name__)


@udaap_bp.post("/loan-applications/<application_id>/udaap-reviews")
def udaap_create(application_id):
    require_role(ROLE_COMPLIANCE_OFFICER)
    application = la_svc.get_or_404(application_id)
    body = get_json_body()
    r = svc.create(application, g.user_id, body)
    return success(serializers.udaap_review(r), status_code=201)


@udaap_bp.get("/loan-applications/<application_id>/udaap-reviews")
def udaap_list(application_id):
    require_role(ROLE_COMPLIANCE_OFFICER, ROLE_ADMIN)
    la_svc.get_or_404(application_id)
    items = svc.list_for_app(application_id)
    total = len(items)
    return success_list(
        [serializers.udaap_review(i) for i in items],
        total_count=total,
        limit=total if total > 0 else 10,
        offset=0,
    )
