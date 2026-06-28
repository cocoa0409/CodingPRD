"""Lab results read endpoints (PRD 3.11)."""
from flask import Blueprint, request

import common
import errors
import serializers
from db import db
from middleware import require_roles

bp = Blueprint("results", __name__)


@bp.get("/lab-results/<rid>")
@require_roles("OrderingProvider", "LabOps", "BillingAgent")
def get_result(rid):
    rec = db.lab_results.get(rid)
    if rec is None:
        # No lab-result-specific not-found error in the catalog; use order not-found
        # as the closest resource-scoped 404 for this nested result resource.
        errors.fail(errors.ERR_ORDER_NOT_FOUND, "Lab result not found.")
    return common.object_response(serializers.lab_result(rec))


@bp.get("/lab-results")
@require_roles("OrderingProvider", "LabOps", "BillingAgent")
def list_results():
    limit, offset = common.get_pagination()
    items = list(db.lab_results.values())
    lab_partner_id = request.args.get("lab_partner_id")
    if lab_partner_id is not None:
        items = [r for r in items if r["lab_partner_id"] == lab_partner_id]
    lab_order_id = request.args.get("lab_order_id")
    if lab_order_id is not None:
        items = [r for r in items if r["lab_order_id"] == lab_order_id]
    items = common.sort_by_created(items)
    page, total = common.paginate(items, limit, offset)
    return common.array_response([serializers.lab_result(r) for r in page], limit, offset, total)
