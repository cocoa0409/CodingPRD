"""Read endpoints for MaintenanceFee."""

from flask import Blueprint, request

from db import db
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from services.pagination import parse_pagination, slice_sorted
from services.serialize import maintenance_fee_to_wire


bp = Blueprint("maintenance_fees", __name__)


@bp.route("/maintenance-fees/<mid>", methods=["GET"])
@require_roles("Applicant", "USPTOAdmin")
def get_maintenance_fee(mid, **_):
    mf = db.maintenance_fees.get(mid)
    if mf is None:
        raise_api(
            "ERR_APPLICATION_NOT_FOUND", f"MaintenanceFee {mid} not found"
        )
    return success(maintenance_fee_to_wire(mf))


@bp.route("/maintenance-fees", methods=["GET"])
@require_roles("Applicant", "USPTOAdmin")
def list_maintenance_fees(**_):
    limit, offset = parse_pagination()
    app_filter = request.args.get("application_id")
    items = []
    for mf in db.maintenance_fees.values():
        if app_filter and mf["application_id"] != app_filter:
            continue
        items.append(mf)
    page, total = slice_sorted(items, limit, offset)
    return list_success(
        [maintenance_fee_to_wire(m) for m in page], limit, offset, total
    )
