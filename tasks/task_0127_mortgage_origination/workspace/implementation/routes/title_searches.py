"""TitleSearch endpoints."""

from flask import Blueprint

from config import ROLE_LOAN_OFFICER
from middleware import require_role
from response import get_json_body, success
from services import loan_applications as la_svc, serializers, title_searches as svc


title_searches_bp = Blueprint("title_searches", __name__)


@title_searches_bp.post("/loan-applications/<application_id>/title-search")
def title_create(application_id):
    require_role(ROLE_LOAN_OFFICER)
    application = la_svc.get_or_404(application_id)
    body = get_json_body()
    ts = svc.create(application, body)
    return success(serializers.title_search(ts), status_code=201)


@title_searches_bp.post("/loan-applications/<application_id>/title-search/complete")
def title_complete(application_id):
    require_role(ROLE_LOAN_OFFICER)
    application = la_svc.get_or_404(application_id)
    body = get_json_body()
    ts = svc.complete(application, body)
    return success(serializers.title_search(ts))


@title_searches_bp.post("/loan-applications/<application_id>/title-search/resolve")
def title_resolve(application_id):
    require_role(ROLE_LOAN_OFFICER)
    application = la_svc.get_or_404(application_id)
    body = get_json_body()
    ts = svc.resolve(application, body)
    return success(serializers.title_search(ts))
