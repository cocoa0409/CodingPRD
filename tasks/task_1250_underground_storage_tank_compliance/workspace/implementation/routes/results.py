"""ResultRecord ledger reads (PRD 3.4-3.5). Immutable: no write endpoints."""
from flask import Blueprint

from authz import READ_ROLES, require_roles
from db import store
from errors import result_record_not_found
from respond import success
from serialize import ser_result_record
from store_ops import get_or_404, paginate, qparam, sorted_by_creation

bp = Blueprint("result_records", __name__)


@bp.route("/result-records", methods=["GET"])
def list_result_records():
    require_roles(READ_ROLES)
    service_order_id = qparam("service_order_id")
    outcome = qparam("outcome")
    items = store.result_records.values()
    if service_order_id is not None:
        items = [r for r in items if r["service_order_id"] == service_order_id]
    if outcome is not None:
        items = [r for r in items if r["outcome"] == outcome]
    # Ordering pinned to created_at ASC (oldest first) for deterministic replay.
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_result_record(r) for r in page], response_type="array",
                   pagination=pagination)


@bp.route("/result-records/<rec_id>", methods=["GET"])
def get_result_record(rec_id):
    require_roles(READ_ROLES)
    return success(ser_result_record(get_or_404(store.result_records, rec_id,
                                                result_record_not_found)))
