"""Payments: post (OCC-guarded), get/list, reverse (PRD §3.9, §2.10)."""

from flask import Blueprint, request, g

import db
from errors import ApiError
from middleware import require_roles
from response import success, list_success
from services.common import (
    get_json_body, require_fields, serialize,
    pagination_params, paginate, sort_by_creation,
)
from services.calculations import recompute_statement_totals

payments_bp = Blueprint("payments", __name__)

PAYABLE_STATES = {"UNPAID", "PARTIALLY_PAID", "DELINQUENT"}


def _statement_lease(stmt):
    return db.leases.get(stmt["lease_id"])


@payments_bp.route("/statements/<statement_id>/payments", methods=["POST"])
@require_roles("Tenant", "PropertyManager")
def post_payment(statement_id):
    stmt = db.tenant_statements.get(statement_id)
    if stmt is None:
        raise ApiError("ERR_NOT_FOUND", "TenantStatement not found")

    # Tenant ownership (priority 4).
    if g.user_role == "Tenant":
        lease = _statement_lease(stmt)
        if lease is None or lease["tenant_user_id"] != g.user_id:
            raise ApiError("ERR_NOT_STATEMENT_OWNER", "Tenant does not own this statement")

    body = get_json_body()
    require_fields(body, "amount_cents", "expected_statement_version")
    amount_cents = body["amount_cents"]
    if (not isinstance(amount_cents, int) or isinstance(amount_cents, bool)
            or amount_cents <= 0):
        raise ApiError("ERR_INVALID_REQUEST", "amount_cents must be a positive integer")
    expected_version = body["expected_statement_version"]
    if (not isinstance(expected_version, int) or isinstance(expected_version, bool)):
        raise ApiError("ERR_INVALID_REQUEST", "expected_statement_version must be an integer")

    # State (priority 6).
    if stmt["payment_status"] not in PAYABLE_STATES:
        raise ApiError("ERR_INVALID_STATE", "Statement is not in a payable state")

    # OCC (priority 14, 412) — checked before amount-bound business rule.
    if expected_version != stmt["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_statement_version is stale")

    # Payment amount bound (priority 15, 409).
    if amount_cents > stmt["balance_due_cents"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE", "Payment exceeds balance")

    # Create the Payment.
    payment = {
        "statement_id": statement_id,
        "property_id": stmt["property_id"],
        "tenant_user_id": g.user_id,
        "amount_cents": amount_cents,
        "expected_statement_version": expected_version,
        "status": "POSTED",
    }
    db.stamp_create(payment)
    db.payments[payment["id"]] = payment

    # Apply to statement.
    stmt["amount_paid_cents"] += amount_cents
    recompute_statement_totals(stmt)
    if stmt["balance_due_cents"] <= 0:
        stmt["payment_status"] = "PAID"
    else:
        stmt["payment_status"] = "PARTIALLY_PAID"
    db.touch(stmt)

    return success(serialize(payment), status=201)


@payments_bp.route("/payments/<payment_id>", methods=["GET"])
@require_roles("PropertyManager", "Tenant", "Auditor")
def get_payment(payment_id):
    payment = db.payments.get(payment_id)
    if payment is None:
        raise ApiError("ERR_NOT_FOUND", "Payment not found")
    if g.user_role == "Tenant":
        stmt = db.tenant_statements.get(payment["statement_id"])
        lease = _statement_lease(stmt) if stmt else None
        if lease is None or lease["tenant_user_id"] != g.user_id:
            raise ApiError("ERR_NOT_STATEMENT_OWNER", "Tenant does not own this payment")
    return success(serialize(payment), status=200)


@payments_bp.route("/payments", methods=["GET"])
@require_roles("PropertyManager", "Tenant", "Auditor")
def list_payments():
    statement_id = request.args.get("statement_id")
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    items = list(db.payments.values())
    if statement_id is not None:
        items = [p for p in items if p["statement_id"] == statement_id]
    if property_id is not None:
        items = [p for p in items if p["property_id"] == property_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]

    if g.user_role == "Tenant":
        items = [p for p in items if p["tenant_user_id"] == g.user_id]

    items = sort_by_creation(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return list_success([serialize(p) for p in page], limit, offset, total)


@payments_bp.route("/payments/<payment_id>/reverse", methods=["POST"])
@require_roles("PropertyManager")
def reverse_payment(payment_id):
    payment = db.payments.get(payment_id)
    if payment is None:
        raise ApiError("ERR_NOT_FOUND", "Payment not found")
    if payment["status"] != "POSTED":
        raise ApiError("ERR_INVALID_STATE", "Payment is not POSTED")

    stmt = db.tenant_statements.get(payment["statement_id"])
    if stmt is None:
        raise ApiError("ERR_NOT_FOUND", "TenantStatement not found")
    cycle = db.billing_cycles.get(stmt["billing_cycle_id"])
    if cycle is not None and cycle["status"] == "CLOSED":
        raise ApiError("ERR_CYCLE_CLOSED", "Parent billing cycle is closed")

    payment["status"] = "REVERSED"
    db.touch(payment)

    # Compensation on the statement.
    stmt["amount_paid_cents"] -= payment["amount_cents"]
    recompute_statement_totals(stmt)
    if stmt["amount_paid_cents"] <= 0:
        stmt["payment_status"] = "UNPAID"
    elif stmt["balance_due_cents"] <= 0:
        stmt["payment_status"] = "PAID"
    else:
        stmt["payment_status"] = "PARTIALLY_PAID"
    db.touch(stmt)

    return success(serialize(payment), status=200)
