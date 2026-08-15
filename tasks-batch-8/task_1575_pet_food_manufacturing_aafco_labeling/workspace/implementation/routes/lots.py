"""BatchLotCode endpoints."""

from flask import Blueprint, request

import errors
from db import store
from middleware import require_roles, get_json_body, parse_pagination, paginate
from response import success_object, success_list
from services.calculations import serialize, serialize_list
from routes.production_batches import _get_batch, _create_lot_for_batch

bp = Blueprint("lots", __name__)


@bp.route("/production-batches/<id>/lots", methods=["POST"])
def create_lot(id):
    require_roles("LineOperator")
    batch = _get_batch(id)
    body = get_json_body()
    lot = _create_lot_for_batch(batch, body)
    return success_object(serialize(lot), 201)


@bp.route("/production-batches/<id>/lots", methods=["GET"])
def list_lots(id):
    require_roles("PlatformAdmin", "LineOperator", "QualityAnalyst", "QAApprover")
    _get_batch(id)
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = [l for l in store.batch_lot_codes.values() if l["batch_id"] == id]
    items.sort(key=lambda e: (e["_created_at_dt"], e["id"]))
    if status_filter is not None:
        items = [l for l in items if l["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total, 200)
