"""SettlementBatch routes."""

from flask import Blueprint, g, request

from db import LOCK
from middleware import require_roles
from response import success_array, success_object, parse_pagination
from services.settlement import (
    create_batch,
    get_batch,
    list_batches,
    lock_batch,
    serialize_batch,
    settle_batch,
)


bp = Blueprint("settlements", __name__)


@bp.route("/settlements", methods=["POST"])
@require_roles("OperationsAdmin")
def post_settlement():
    with LOCK:
        b = create_batch(request.get_json(silent=True) or {}, g.user_id)
        return success_object(serialize_batch(b), 201)


@bp.route("/settlements", methods=["GET"])
@require_roles("OperationsAdmin")
def get_settlements():
    with LOCK:
        limit, offset = parse_pagination(request.args)
        all_records = list_batches(request.args)
        sliced = all_records[offset: offset + limit]
        return success_array(
            [serialize_batch(b) for b in sliced],
            limit=limit, offset=offset, total_count=len(all_records),
        )


@bp.route("/settlements/<batch_id>", methods=["GET"])
@require_roles("OperationsAdmin")
def get_one_settlement(batch_id):
    with LOCK:
        b = get_batch(batch_id)
        return success_object(serialize_batch(b))


@bp.route("/settlements/<batch_id>/lock", methods=["POST"])
@require_roles("OperationsAdmin")
def post_lock(batch_id):
    with LOCK:
        b = lock_batch(batch_id, request.get_json(silent=True) or {}, g.user_id)
        return success_object(serialize_batch(b))


@bp.route("/settlements/<batch_id>/settle", methods=["POST"])
@require_roles("OperationsAdmin")
def post_settle(batch_id):
    with LOCK:
        b = settle_batch(batch_id, request.get_json(silent=True) or {}, g.user_id)
        return success_object(serialize_batch(b))
