"""/vouchers routes."""

from flask import Blueprint, request

from app import store
from app.envelope import list_response, success_response
from app.errors import forbidden_role, not_found
from app.routes._helpers import get_json_body, query_bool, with_auth
from app.serializers import serialize_voucher
from app.services import vouchers as svc
from app.services.common import parse_pagination, paginate, sort_by_created_at


bp = Blueprint("vouchers", __name__)


@bp.post("/vouchers")
@with_auth("CaseWorker")
def issue_voucher(caller=None):
    body = get_json_body()
    with store.lock():
        record = svc.issue_voucher(body)
    return success_response(serialize_voucher(record), status=201)


@bp.get("/vouchers/<voucher_id>")
@with_auth("Applicant", "CaseWorker", "PHAAdmin", "PortabilityCoordinator")
def get_voucher(voucher_id, caller=None):
    record = store.vouchers.get(voucher_id)
    if record is None:
        raise not_found("Voucher not found")
    if caller.role == "Applicant" and record.get("applicant_id") != caller.user_id:
        raise forbidden_role("Applicant may only read its own voucher")
    return success_response(serialize_voucher(record))


@bp.get("/vouchers")
@with_auth("CaseWorker", "PHAAdmin")
def list_vouchers(caller=None):
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    pha = request.args.get("administering_pha_id")
    smf = query_bool("special_mobility_flag")
    rows = svc.list_vouchers(status=status, administering_pha_id=pha, special_mobility_flag=smf)
    rows = sort_by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return list_response((serialize_voucher(v) for v in page), limit=limit, offset=offset, total=total)
