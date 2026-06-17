"""Invoice endpoints — payment, past-due, void (PRD §3.7, §2.7 OCC)."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
from helpers import (get_json, require_int, pagination_params, paginate)
from services.derived import recompute_open_invoice_balance

bp = Blueprint("invoices", __name__)


def invoice_view(inv):
    return {
        "id": inv["id"],
        "operator_id": inv["operator_id"],
        "service_visit_id": inv["service_visit_id"],
        "total_cents": inv["total_cents"],
        "paid_cents": inv["paid_cents"],
        "status": inv["status"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
    }


@bp.route("/invoices/<id>", methods=["GET"])
def get_invoice(id):
    user_id, role = authenticate()
    require_role(role, {"BillingClerk", "LineManager", "Operator"})
    inv = db.invoices.get(id)
    if inv is None:
        raise err(errors.ERR_NOT_FOUND, "Invoice not found.")
    if role == "Operator" and user_id != inv["operator_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Operator may read only its own invoices.")
    return success(invoice_view(inv), 200)


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    user_id, role = authenticate()
    require_role(role, {"BillingClerk", "LineManager", "Operator"})
    limit, offset = pagination_params()
    records = list(db.invoices.values())
    if role == "Operator":
        records = [r for r in records if r["operator_id"] == user_id]
    op_f = request.args.get("operator_id")
    v_f = request.args.get("service_visit_id")
    st_f = request.args.get("status")
    if op_f is not None:
        records = [r for r in records if r["operator_id"] == op_f]
    if v_f is not None:
        records = [r for r in records if r["service_visit_id"] == v_f]
    if st_f is not None:
        records = [r for r in records if r["status"] == st_f]
    window, total = paginate(records, limit, offset)
    return list_response([invoice_view(r) for r in window], limit, offset, total)


@bp.route("/invoices/<id>/pay", methods=["POST"])
def pay(id):
    _, role = authenticate()
    require_role(role, {"BillingClerk"})
    inv = db.invoices.get(id)
    if inv is None:
        raise err(errors.ERR_NOT_FOUND, "Invoice not found.")
    body = get_json()
    payment_cents = require_int(body, "payment_cents")
    expected_version = require_int(body, "expected_invoice_version")

    # State eligibility: pay defined from ISSUED or PAST_DUE.
    if inv["status"] not in ("ISSUED", "PAST_DUE"):
        raise err(errors.ERR_INVALID_STATE, "pay requires ISSUED or PAST_DUE status.")
    # OCC check before fiscal check (§3.10 ordering).
    if expected_version != inv["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale invoice version.")
    # Fiscal: payment_cents >= 1 and paid+payment must not exceed total.
    if payment_cents < 1 or inv["paid_cents"] + payment_cents > inv["total_cents"]:
        raise err(errors.ERR_OVERPAYMENT, "Invalid or overpaying payment amount.")

    inv["paid_cents"] += payment_cents
    if inv["paid_cents"] >= inv["total_cents"]:
        inv["status"] = "PAID"
    db.touch(inv)

    operator = db.operators.get(inv["operator_id"])
    recompute_open_invoice_balance(operator)
    # When a PAST_DUE invoice is paid in full and the operator no longer has any
    # ISSUED/PAST_DUE invoice carrying a positive balance, restore ACTIVE.
    if inv["status"] == "PAID" and operator is not None:
        has_positive = any(
            i["operator_id"] == operator["id"]
            and i["status"] in ("ISSUED", "PAST_DUE")
            and (i["total_cents"] - i["paid_cents"]) > 0
            for i in db.invoices.values()
        )
        if not has_positive and operator["account_status"] == "SUSPENDED":
            operator["account_status"] = "ACTIVE"
            db.touch(operator)
    return success(invoice_view(inv), 200)


@bp.route("/invoices/<id>/mark-past-due", methods=["POST"])
def mark_past_due(id):
    _, role = authenticate()
    require_role(role, {"BillingClerk"})
    inv = db.invoices.get(id)
    if inv is None:
        raise err(errors.ERR_NOT_FOUND, "Invoice not found.")
    if inv["status"] != "ISSUED":
        raise err(errors.ERR_INVALID_STATE, "mark-past-due requires ISSUED status.")
    inv["status"] = "PAST_DUE"
    db.touch(inv)
    operator = db.operators.get(inv["operator_id"])
    if operator is not None:
        operator["account_status"] = "SUSPENDED"
        db.touch(operator)
    return success(invoice_view(inv), 200)


@bp.route("/invoices/<id>/void", methods=["POST"])
def void(id):
    _, role = authenticate()
    require_role(role, {"LineManager"})
    inv = db.invoices.get(id)
    if inv is None:
        raise err(errors.ERR_NOT_FOUND, "Invoice not found.")
    if inv["status"] != "ISSUED":
        raise err(errors.ERR_INVALID_STATE, "void requires ISSUED status.")
    inv["status"] = "VOID"
    db.touch(inv)
    operator = db.operators.get(inv["operator_id"])
    if operator is not None:
        recompute_open_invoice_balance(operator)
    return success(invoice_view(inv), 200)
