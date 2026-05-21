"""/portability-requests routes."""

from flask import Blueprint

from app import store
from app.envelope import success_response
from app.errors import forbidden_role
from app.routes._helpers import get_json_body, with_auth
from app.serializers import serialize_portability
from app.services import portability as svc


bp = Blueprint("portability", __name__)


@bp.post("/portability-requests")
@with_auth("Applicant", "CaseWorker")
def create_request(caller=None):
    body = get_json_body()
    # If the caller is an Applicant, enforce ownership of the voucher.
    if caller.role == "Applicant":
        voucher_id = body.get("voucher_id") if isinstance(body, dict) else None
        voucher = store.vouchers.get(voucher_id) if voucher_id else None
        if voucher is None or voucher.get("applicant_id") != caller.user_id:
            raise forbidden_role("Applicant may only request portability on own voucher")
    with store.lock():
        record = svc.create_request(body)
    return success_response(serialize_portability(record), status=201)


@bp.post("/portability-requests/<req_id>/absorb")
@with_auth("PortabilityCoordinator")
def absorb(req_id, caller=None):
    body = get_json_body()
    with store.lock():
        record = svc.absorb(req_id, body)
    return success_response(serialize_portability(record))


@bp.post("/portability-requests/<req_id>/bill")
@with_auth("PortabilityCoordinator")
def bill(req_id, caller=None):
    body = get_json_body()
    with store.lock():
        record = svc.bill(req_id, body)
    return success_response(serialize_portability(record))


@bp.post("/portability-requests/<req_id>/deny")
@with_auth("PortabilityCoordinator")
def deny(req_id, caller=None):
    body = get_json_body()
    with store.lock():
        record = svc.deny(req_id, body)
    return success_response(serialize_portability(record))
