"""/applicants routes."""

from flask import Blueprint

from app import store
from app.envelope import success_response
from app.errors import forbidden_role, not_found
from app.routes._helpers import get_json_body, with_auth
from app.serializers import serialize_applicant
from app.services import applicants as svc


bp = Blueprint("applicants", __name__)


@bp.post("/applicants")
@with_auth("Applicant", "CaseWorker")
def create_applicant(caller=None):
    body = get_json_body()
    with store.lock():
        record = svc.create_applicant(body)
    return success_response(serialize_applicant(record), status=201)


@bp.get("/applicants/<applicant_id>")
@with_auth("Applicant", "CaseWorker", "PHAAdmin")
def get_applicant(applicant_id, caller=None):
    record = store.applicants.get(applicant_id)
    if record is None:
        raise not_found("Applicant not found")
    if caller.role == "Applicant" and record["id"] != caller.user_id:
        raise forbidden_role("Applicant may only read its own record")
    return success_response(serialize_applicant(record))


@bp.post("/applicants/<applicant_id>/revoke")
@with_auth("PHAAdmin")
def revoke_applicant(applicant_id, caller=None):
    body = get_json_body()
    with store.lock():
        record = svc.revoke_applicant(applicant_id, body)
    return success_response(serialize_applicant(record))
