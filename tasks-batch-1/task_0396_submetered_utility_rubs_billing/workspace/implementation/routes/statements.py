"""TenantStatement: get/list, mark-delivered, late-fee, collections (PRD §3.8, §3.10)."""

from datetime import timedelta

from flask import Blueprint, request, g

import db
from errors import ApiError
from middleware import require_roles
from response import success, list_success
from services.common import (
    serialize, parse_date_field,
    pagination_params, paginate, sort_by_creation,
)
from services.calculations import (
    late_fee, recompute_statement_totals, GRACE_DAYS, COLLECTIONS_GRACE_DAYS,
)

statements_bp = Blueprint("statements", __name__)


def _statement_lease(stmt):
    return db.leases.get(stmt["lease_id"])


def _parent_cycle(stmt):
    return db.billing_cycles.get(stmt["billing_cycle_id"])


@statements_bp.route("/statements/<statement_id>", methods=["GET"])
@require_roles("PropertyManager", "Tenant", "Auditor")
def get_statement(statement_id):
    stmt = db.tenant_statements.get(statement_id)
    if stmt is None:
        raise ApiError("ERR_NOT_FOUND", "TenantStatement not found")
    if g.user_role == "Tenant":
        lease = _statement_lease(stmt)
        if lease is None or lease["tenant_user_id"] != g.user_id:
            raise ApiError("ERR_NOT_STATEMENT_OWNER", "Tenant does not own this statement")
    return success(serialize(stmt), status=200)


@statements_bp.route("/statements", methods=["GET"])
@require_roles("PropertyManager", "Tenant", "Auditor")
def list_statements():
    billing_cycle_id = request.args.get("billing_cycle_id")
    lease_id = request.args.get("lease_id")
    unit_id = request.args.get("unit_id")
    property_id = request.args.get("property_id")
    payment_status = request.args.get("payment_status")
    items = list(db.tenant_statements.values())
    if billing_cycle_id is not None:
        items = [s for s in items if s["billing_cycle_id"] == billing_cycle_id]
    if lease_id is not None:
        items = [s for s in items if s["lease_id"] == lease_id]
    if unit_id is not None:
        items = [s for s in items if s["unit_id"] == unit_id]
    if property_id is not None:
        items = [s for s in items if s["property_id"] == property_id]
    if payment_status is not None:
        items = [s for s in items if s["payment_status"] == payment_status]

    # Tenants only see their own statements.
    if g.user_role == "Tenant":
        owned = []
        for s in items:
            lease = _statement_lease(s)
            if lease is not None and lease["tenant_user_id"] == g.user_id:
                owned.append(s)
        items = owned

    items = sort_by_creation(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return list_success([serialize(s) for s in page], limit, offset, total)


@statements_bp.route("/statements/<statement_id>/mark-delivered", methods=["POST"])
@require_roles("PropertyManager")
def mark_delivered(statement_id):
    stmt = db.tenant_statements.get(statement_id)
    if stmt is None:
        raise ApiError("ERR_NOT_FOUND", "TenantStatement not found")
    if stmt["delivery_status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Statement is not ISSUED")
    stmt["delivery_status"] = "DELIVERED"
    db.touch(stmt)
    return success(serialize(stmt), status=200)


@statements_bp.route("/statements/<statement_id>/assess-late-fee", methods=["POST"])
@require_roles("PropertyManager")
def assess_late_fee(statement_id):
    stmt = db.tenant_statements.get(statement_id)
    if stmt is None:
        raise ApiError("ERR_NOT_FOUND", "TenantStatement not found")

    if stmt["payment_status"] not in ("UNPAID", "PARTIALLY_PAID"):
        raise ApiError("ERR_INVALID_STATE", "Statement is not in a delinquency-eligible state")

    clock_date = db.get_clock().date()
    due_date = parse_date_field(stmt["due_date"], "due_date")
    threshold = due_date + timedelta(days=GRACE_DAYS)
    if not (clock_date > threshold):
        raise ApiError("ERR_NOT_YET_DELINQUENT", "Not yet past grace window")
    if stmt["balance_due_cents"] <= 0:
        raise ApiError("ERR_NOT_YET_DELINQUENT", "No outstanding balance")

    fee = late_fee(stmt["balance_due_cents"])
    stmt["late_fee_cents"] += fee
    recompute_statement_totals(stmt)
    stmt["payment_status"] = "DELINQUENT"
    db.touch(stmt)
    return success(serialize(stmt), status=200)


@statements_bp.route("/statements/<statement_id>/send-to-collections", methods=["POST"])
@require_roles("PropertyManager")
def send_to_collections(statement_id):
    stmt = db.tenant_statements.get(statement_id)
    if stmt is None:
        raise ApiError("ERR_NOT_FOUND", "TenantStatement not found")

    if stmt["payment_status"] != "DELINQUENT":
        raise ApiError("ERR_INVALID_STATE", "Statement is not DELINQUENT")
    if stmt["balance_due_cents"] <= 0:
        raise ApiError("ERR_NOT_YET_COLLECTIONS", "No outstanding balance")

    clock_date = db.get_clock().date()
    due_date = parse_date_field(stmt["due_date"], "due_date")
    threshold = due_date + timedelta(days=COLLECTIONS_GRACE_DAYS)
    if not (clock_date >= threshold):
        raise ApiError("ERR_NOT_YET_COLLECTIONS", "Not yet past collections window")

    stmt["payment_status"] = "IN_COLLECTIONS"
    db.touch(stmt)
    return success(serialize(stmt), status=200)
