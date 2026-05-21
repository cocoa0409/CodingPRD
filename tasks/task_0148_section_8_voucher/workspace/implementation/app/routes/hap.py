"""/hap-payments routes."""

from flask import Blueprint, request

from app.envelope import list_response
from app.routes._helpers import with_auth
from app.serializers import serialize_hap_payment
from app.services import hap as svc
from app.services.common import parse_pagination, paginate, sort_by_created_at


bp = Blueprint("hap", __name__)


@bp.get("/hap-payments")
@with_auth("CaseWorker", "PHAAdmin", "Landlord")
def list_payments(caller=None):
    limit, offset = parse_pagination(request.args)
    tenancy_id = request.args.get("tenancy_id")
    month = request.args.get("pay_period_month")
    status = request.args.get("status")
    landlord_filter = caller.user_id if caller.role == "Landlord" else None
    rows = svc.list_payments(tenancy_id=tenancy_id, pay_period_month=month, status=status, landlord_id_filter=landlord_filter)
    rows = sort_by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return list_response((serialize_hap_payment(h) for h in page), limit=limit, offset=offset, total=total)
