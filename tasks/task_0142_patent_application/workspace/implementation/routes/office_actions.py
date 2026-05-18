"""Office Action endpoints (SCAFFOLD §1.5).

GET    /office-actions/{id}             -> Applicant, Examiner, USPTOAdmin
POST   /office-actions/{id}/responses   -> Applicant
"""

from flask import Blueprint

from config import ROLE_APPLICANT, ROLE_EXAMINER, ROLE_USPTO_ADMIN
from db import store
from errors import make_error
from middleware import require_auth
from response import success
from services.patent_engine import _check_ownership_application, file_response
from services.serializers import serialize_office_action, serialize_response


office_actions_bp = Blueprint("office_actions", __name__)


@office_actions_bp.get("/office-actions/<oa_id>")
@require_auth(allowed_roles=[ROLE_APPLICANT, ROLE_EXAMINER, ROLE_USPTO_ADMIN])
def get_office_action_route(oa_id: str):
    oa = store.office_actions.get(oa_id)
    if oa is None:
        raise make_error("ERR_NOT_FOUND", f"OfficeAction {oa_id} not found.")
    # Ownership via owning application
    application = store.applications.get(oa["application_id"])
    if application is not None:
        _check_ownership_application(application)
    return success(serialize_office_action(oa))


@office_actions_bp.post("/office-actions/<oa_id>/responses")
@require_auth(allowed_roles=[ROLE_APPLICANT])
def create_response_route(oa_id: str):
    with store.lock:
        resp = file_response(oa_id)
    return success(serialize_response(resp), status=201)
