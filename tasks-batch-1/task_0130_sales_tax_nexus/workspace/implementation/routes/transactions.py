"""Transaction + TransactionLineItem endpoints, including the parallel
settlement/audit state machines (§3.3-3.6)."""
from flask import Blueprint, request

import db
from errors import (
    APIError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_SELLER_SUSPENDED, ERR_TRANSACTION_LOCKED,
)
from middleware import require
from response import object_response, array_response
from services import common, serializers, settlement

bp = Blueprint("transactions", __name__)

READ_ROLES = ["Seller", "PlatformAdmin", "TaxPreparer", "TaxApprover", "Auditor"]


# ---------------------------------------------------------------------------
# Transaction CRUD
# ---------------------------------------------------------------------------
@bp.post("/transactions")
@require("Seller")
def create_transaction():
    body = common.get_body()
    seller_id = common.require_str(body, "seller_id")
    jurisdiction_id = common.require_str(body, "jurisdiction_id")
    facilitator_id = body.get("facilitator_id")
    if facilitator_id is not None and not isinstance(facilitator_id, str):
        raise APIError(ERR_INVALID_REQUEST, "facilitator_id must be a string or null")
    customer_ref = common.require_str(body, "customer_ref")
    customer_exempt_requested = common.require_bool(body, "customer_exempt_requested", default=False)

    common.resolve_fk(db.sellers, seller_id, "seller_id")
    common.resolve_fk(db.tax_jurisdictions, jurisdiction_id, "jurisdiction_id")
    if facilitator_id is not None:
        common.resolve_fk(db.marketplace_facilitators, facilitator_id, "facilitator_id")

    rec = {
        "seller_id": seller_id,
        "jurisdiction_id": jurisdiction_id,
        "facilitator_id": facilitator_id,
        "customer_ref": customer_ref,
        "customer_exempt_requested": customer_exempt_requested,
        "sourcing_used": None,
        "applied_rate": None,
        "taxable_subtotal": 0,
        "tax_collected": 0,
        "remittance_responsibility": None,
        "settlement_status": "PENDING",
        "audit_status": "UNREVIEWED",
        "tax_return_id": None,
        "_sourced_state_id": None,
    }
    common.stamp_create(rec)
    db.transactions[rec["id"]] = rec
    return object_response(serializers.transaction(rec), 201)


@bp.get("/transactions/<rec_id>")
@require(*READ_ROLES)
def get_transaction(rec_id):
    rec = common.get_or_404(db.transactions, rec_id, "transaction")
    return object_response(serializers.transaction(rec))


@bp.get("/transactions")
@require(*READ_ROLES)
def list_transactions():
    records = list(db.transactions.values())
    a = request.args
    if a.get("seller_id") is not None:
        records = [r for r in records if r["seller_id"] == a.get("seller_id")]
    if a.get("jurisdiction_id") is not None:
        records = [r for r in records if r["jurisdiction_id"] == a.get("jurisdiction_id")]
    if a.get("facilitator_id") is not None:
        records = [r for r in records if r["facilitator_id"] == a.get("facilitator_id")]
    if a.get("tax_return_id") is not None:
        records = [r for r in records if r["tax_return_id"] == a.get("tax_return_id")]
    if a.get("settlement_status") is not None:
        records = [r for r in records if r["settlement_status"] == a.get("settlement_status")]
    items, limit, offset, total = common.paginate(records, serializers.transaction)
    return array_response(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Line items
# ---------------------------------------------------------------------------
@bp.post("/line-items")
@require("Seller")
def create_line_item():
    body = common.get_body()
    transaction_id = common.require_str(body, "transaction_id")
    category_code = common.require_str(body, "category_code")
    quantity = common.require_int(body, "quantity", minimum=1)
    unit_price = common.require_number(body, "unit_price", minimum=0, exclusive_min=True)

    txn = common.resolve_fk(db.transactions, transaction_id, "transaction_id")
    if txn["settlement_status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, "line items may only be added to a PENDING transaction")

    rec = {
        "transaction_id": transaction_id,
        "category_code": category_code,
        "quantity": quantity,
        "unit_price": unit_price,
        "line_taxability": None,
        "line_tax": 0,
    }
    common.stamp_create(rec, versioned=False)
    db.line_items[rec["id"]] = rec
    return object_response(serializers.line_item(rec), 201)


@bp.get("/line-items/<rec_id>")
@require(*READ_ROLES)
def get_line_item(rec_id):
    rec = common.get_or_404(db.line_items, rec_id, "line item")
    return object_response(serializers.line_item(rec))


@bp.get("/line-items")
@require(*READ_ROLES)
def list_line_items():
    records = list(db.line_items.values())
    tid = request.args.get("transaction_id")
    if tid is not None:
        records = [r for r in records if r["transaction_id"] == tid]
    items, limit, offset, total = common.paginate(records, serializers.line_item)
    return array_response(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Settlement dimension
# ---------------------------------------------------------------------------
@bp.post("/transactions/<rec_id>/settle")
@require("Seller")
def settle_transaction(rec_id):
    txn = common.get_or_404(db.transactions, rec_id, "transaction")
    # State checks (priority 10) then seller-suspension gate (priority 14).
    if txn["settlement_status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, "transaction must be PENDING to settle")
    has_lines = any(li["transaction_id"] == txn["id"] for li in db.line_items.values())
    if not has_lines:
        raise APIError(ERR_INVALID_STATE, "transaction has no line items")
    seller = db.sellers.get(txn["seller_id"])
    if seller is not None and seller["status"] == "SUSPENDED":
        raise APIError(ERR_SELLER_SUSPENDED, "seller is suspended")

    settlement.settle(txn)
    common.touch(txn)
    common.append_audit(txn["seller_id"], "Transaction", txn["id"], "SETTLE")
    return object_response(serializers.transaction(txn))


@bp.post("/transactions/<rec_id>/void")
@require("Seller")
def void_transaction(rec_id):
    txn = common.get_or_404(db.transactions, rec_id, "transaction")
    if txn["settlement_status"] != "SETTLED":
        raise APIError(ERR_INVALID_STATE, "transaction must be SETTLED to void")
    if txn["tax_return_id"] is not None:
        raise APIError(ERR_TRANSACTION_LOCKED, "transaction is swept into a return and locked")

    settlement.void(txn)
    common.touch(txn)
    common.append_audit(txn["seller_id"], "Transaction", txn["id"], "VOID")
    return object_response(serializers.transaction(txn))


# ---------------------------------------------------------------------------
# Audit dimension (independent of settlement)
# ---------------------------------------------------------------------------
@bp.post("/transactions/<rec_id>/flag")
@require("Auditor")
def flag_transaction(rec_id):
    txn = common.get_or_404(db.transactions, rec_id, "transaction")
    if txn["audit_status"] != "UNREVIEWED":
        raise APIError(ERR_INVALID_STATE, "transaction must be UNREVIEWED to flag")
    txn["audit_status"] = "FLAGGED"
    common.touch(txn)
    common.append_audit(txn["seller_id"], "Transaction", txn["id"], "FLAG")
    return object_response(serializers.transaction(txn))


@bp.post("/transactions/<rec_id>/clear")
@require("Auditor")
def clear_transaction(rec_id):
    txn = common.get_or_404(db.transactions, rec_id, "transaction")
    if txn["audit_status"] != "FLAGGED":
        raise APIError(ERR_INVALID_STATE, "transaction must be FLAGGED to clear")
    txn["audit_status"] = "CLEARED"
    common.touch(txn)
    common.append_audit(txn["seller_id"], "Transaction", txn["id"], "CLEAR")
    return object_response(serializers.transaction(txn))
