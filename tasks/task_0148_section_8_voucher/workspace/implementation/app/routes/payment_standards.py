"""/payment-standards routes."""

from flask import Blueprint, request

from app import store
from app.envelope import list_response, success_response
from app.routes._helpers import get_json_body, query_bool, query_int, with_auth
from app.serializers import serialize_payment_standard
from app.services import payment_standards as svc
from app.services.common import parse_pagination, paginate, sort_by_created_at


bp = Blueprint("payment_standards", __name__)


@bp.post("/payment-standards")
@with_auth("PHAAdmin")
def create_payment_standard(caller=None):
    body = get_json_body()
    with store.lock():
        record = svc.create_payment_standard(body)
    return success_response(serialize_payment_standard(record), status=201)


@bp.get("/payment-standards")
@with_auth("PHAAdmin", "CaseWorker", "Landlord")
def list_payment_standards(caller=None):
    limit, offset = parse_pagination(request.args)
    zone = request.args.get("zone")
    bedroom_size = query_int("bedroom_size")
    active_only = query_bool("active_only") or False
    rows = svc.list_payment_standards(zone=zone, bedroom_size=bedroom_size, active_only=active_only)
    rows = sort_by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return list_response((serialize_payment_standard(p) for p in page), limit=limit, offset=offset, total=total)
