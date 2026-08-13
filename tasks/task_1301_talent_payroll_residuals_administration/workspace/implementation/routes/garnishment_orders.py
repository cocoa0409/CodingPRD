"""GarnishmentOrder endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_RESOURCE_INVALID_STATE, ERR_GARNISHMENT_SPEC_INVALID,
)
from helpers import (
    new_id, now_timestamp, require_enum, require_int, require_string,
    err_validation,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, list_response
from serializers import serialize, get_or_404, bump_version

bp = Blueprint("garnishment_orders", __name__)

ORDER_TYPES = {"CHILD_SUPPORT", "FEDERAL_TAX_LEVY", "STATE_TAX_LEVY", "CREDITOR_JUDGMENT"}


@bp.post("/payroll/garnishment-orders")
def create_garnishment_order():
    require_roles({"PayrollAdmin"})
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object")

    performer_id = require_string(body, "performer_id")
    creditor_name = require_string(body, "creditor_name")
    order_type = require_enum(body, "order_type", ORDER_TYPES)
    priority_rank = require_int(body, "priority_rank")

    pct_of_disposable = body.get("pct_of_disposable")
    fixed_amount_cents = body.get("fixed_amount_cents")

    # Type/shape checks on the optional pair when present
    if pct_of_disposable is not None:
        if isinstance(pct_of_disposable, bool) or not isinstance(pct_of_disposable, (int, float)):
            raise err_validation("Field 'pct_of_disposable' must be a number")
    if fixed_amount_cents is not None:
        if isinstance(fixed_amount_cents, bool) or not isinstance(fixed_amount_cents, int):
            raise err_validation("Field 'fixed_amount_cents' must be an integer")

    # FK existence (priority 3)
    get_or_404(db.performers, performer_id, "Performer")

    # Exactly one of pct_of_disposable / fixed_amount_cents (priority 23)
    if (pct_of_disposable is None) == (fixed_amount_cents is None):
        raise ApiError(
            ERR_GARNISHMENT_SPEC_INVALID,
            "Exactly one of pct_of_disposable / fixed_amount_cents must be provided",
            422,
        )

    now = now_timestamp()
    record = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "performer_id": performer_id,
        "creditor_name": creditor_name,
        "order_type": order_type,
        "priority_rank": priority_rank,
        "pct_of_disposable": pct_of_disposable,
        "fixed_amount_cents": fixed_amount_cents,
        "total_withheld_cents": 0,
        "status": "ACTIVE",
    }
    db.garnishment_orders[record["id"]] = record
    return success_object(serialize(record), 201)


@bp.get("/payroll/garnishment-orders")
def list_garnishment_orders():
    require_roles(ALL_ROLES)
    items = list(db.garnishment_orders.values())
    performer_id = request.args.get("performer_id")
    if performer_id is not None:
        items = [o for o in items if o["performer_id"] == performer_id]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_response([serialize(o) for o in items], request.args)


@bp.get("/payroll/garnishment-orders/<order_id>")
def get_garnishment_order(order_id):
    require_roles(ALL_ROLES)
    order = get_or_404(db.garnishment_orders, order_id, "GarnishmentOrder")
    return success_object(serialize(order), 200)


@bp.post("/payroll/garnishment-orders/<order_id>/release")
def release_garnishment_order(order_id):
    require_roles({"PayrollAdmin"})
    order = get_or_404(db.garnishment_orders, order_id, "GarnishmentOrder")

    if order["status"] != "ACTIVE":
        raise ApiError(
            ERR_RESOURCE_INVALID_STATE,
            "Release requires status ACTIVE",
            409,
        )

    order["status"] = "RELEASED"
    bump_version(order)
    return success_object(serialize(order), 200)
