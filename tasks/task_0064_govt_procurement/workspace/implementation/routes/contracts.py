"""Contract routes."""

from flask import Blueprint

from common import get_json_body
from middleware import require_roles
from response import success
from services import contract as svc


bp = Blueprint("contracts", __name__, url_prefix="/procurement")


@bp.post("/contracts")
@require_roles("ProcurementOfficer")
def file_contract():
    body = get_json_body()
    return success(svc.file_contract(body), 201)


@bp.post("/contracts/<cid>/sign")
@require_roles("ProcurementOfficer")
def sign(cid):
    return success(svc.sign_contract(cid), 200)


@bp.post("/contracts/<cid>/begin-amendment")
@require_roles("ProcurementOfficer")
def begin_amend(cid):
    return success(svc.begin_amendment(cid), 200)


@bp.post("/contracts/<cid>/file-amendment")
@require_roles("ProcurementOfficer")
def file_amend(cid):
    body = get_json_body()
    return success(svc.file_amendment(cid, body), 201)


@bp.post("/contracts/<cid>/record-payment")
@require_roles("ProcurementOfficer", "Regulator")
def record_payment(cid):
    body = get_json_body()
    return success(svc.record_payment(cid, body), 200)


@bp.post("/contracts/<cid>/mark-executed")
@require_roles("ProcurementOfficer")
def mark_executed(cid):
    return success(svc.mark_executed(cid), 200)


@bp.post("/contracts/<cid>/terminate")
@require_roles("Regulator")
def terminate(cid):
    body = get_json_body()
    return success(svc.terminate_contract(cid, body), 200)
