"""/tenancies routes."""

from flask import Blueprint

from app import store
from app.envelope import success_response
from app.errors import forbidden_role, not_found
from app.routes._helpers import get_json_body, with_auth
from app.serializers import serialize_tenancy
from app.services import tenancies as svc


bp = Blueprint("tenancies", __name__)


def _ownership_visible(caller, tenancy: dict) -> bool:
    if caller.role == "Applicant":
        voucher = store.vouchers.get(tenancy["voucher_id"])
        return voucher is not None and voucher.get("applicant_id") == caller.user_id
    if caller.role == "Landlord":
        unit = store.units.get(tenancy["unit_id"])
        return unit is not None and unit.get("landlord_id") == caller.user_id
    return True


@bp.post("/tenancies")
@with_auth("Landlord", "CaseWorker")
def create_tenancy(caller=None):
    body = get_json_body()
    with store.lock():
        record = svc.create_tenancy(body)
    return success_response(serialize_tenancy(record), status=201)


@bp.get("/tenancies/<tenancy_id>")
@with_auth("Landlord", "CaseWorker", "Inspector", "Applicant")
def get_tenancy(tenancy_id, caller=None):
    record = store.tenancies.get(tenancy_id)
    if record is None:
        raise not_found("Tenancy not found")
    if not _ownership_visible(caller, record):
        raise forbidden_role("Caller is not the owner of this tenancy")
    return success_response(serialize_tenancy(record))


@bp.post("/tenancies/<tenancy_id>/finalize")
@with_auth("CaseWorker")
def finalize_tenancy(tenancy_id, caller=None):
    body = get_json_body()
    with store.lock():
        record = svc.finalize_tenancy(tenancy_id, body)
    return success_response(serialize_tenancy(record))


@bp.post("/tenancies/<tenancy_id>/move-out")
@with_auth("CaseWorker")
def move_out(tenancy_id, caller=None):
    body = get_json_body()
    with store.lock():
        record = svc.move_out(tenancy_id, body)
    return success_response(serialize_tenancy(record))
