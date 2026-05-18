"""Transaction endpoints (append-only event log)."""
from __future__ import annotations

from flask import Blueprint, g, request

from db import store
from middleware import require_auth
from response import list_success, success
from services.serializers import transaction_view
from services.trust_engine import create_transaction
from utils import parse_iso

from routes._helpers import (
    PRINCIPAL_OR_INCOME,
    TXN_TYPES,
    enforce_grantor_owns_trust,
    enforce_trustee_is_under_trust,
    get_json,
    get_transaction_or_404,
    get_trust_or_404,
    paginate,
    parse_pagination,
    require_date,
    require_enum,
    require_money,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("transactions", __name__)


@bp.post("/trusts/<trust_id>/transactions")
@require_auth(["Trustee"])
def create_transaction_route(trust_id):
    body = get_json()
    txn_type = require_enum(body, "txn_type", TXN_TYPES)
    amount = require_money(body, "amount")
    transaction_date = require_date(body, "transaction_date")
    principal_or_income = require_enum(body, "principal_or_income", PRINCIPAL_OR_INCOME)
    description = require_string(body, "description")
    with store.lock:
        t = get_trust_or_404(trust_id)
        enforce_trustee_is_under_trust(t)
        tx = create_transaction(
            t,
            txn_type=txn_type,
            amount=amount,
            transaction_date=transaction_date,
            principal_or_income=principal_or_income,
            description=description,
        )
        return success(transaction_view(tx), 201)


@bp.get("/trusts/<trust_id>/transactions/<transaction_id>")
@require_auth(["Grantor", "Trustee", "TaxPreparer", "Auditor"])
def read_transaction(trust_id, transaction_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        if g.role == "Grantor":
            enforce_grantor_owns_trust(t)
        if g.role == "Trustee":
            enforce_trustee_is_under_trust(t)
        tx = get_transaction_or_404(t, transaction_id)
        return success(transaction_view(tx), 200)


@bp.get("/trusts/<trust_id>/transactions")
@require_auth(["Grantor", "Trustee", "TaxPreparer", "Auditor"])
def list_transactions(trust_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        if g.role == "Grantor":
            enforce_grantor_owns_trust(t)
        if g.role == "Trustee":
            enforce_trustee_is_under_trust(t)
        items = [tx for tx in store.transactions.values() if tx["trust_id"] == t["id"]]
        # Filters.
        ty_id = request.args.get("tax_year_id")
        if ty_id:
            items = [tx for tx in items if tx["tax_year_id"] == ty_id]
        txn_type_q = request.args.get("txn_type")
        if txn_type_q:
            items = [tx for tx in items if tx["txn_type"] == txn_type_q]
        from_raw = request.args.get("from")
        to_raw = request.args.get("to")
        if from_raw:
            try:
                d_from = parse_iso(from_raw)
                items = [tx for tx in items if tx["transaction_date"] >= d_from]
            except Exception:
                pass
        if to_raw:
            try:
                d_to = parse_iso(to_raw)
                items = [tx for tx in items if tx["transaction_date"] <= d_to]
            except Exception:
                pass
        items = sort_by_created_at(items)
        limit, offset = parse_pagination()
        total = len(items)
        page = paginate(items, limit, offset)
        return list_success([transaction_view(tx) for tx in page], limit, offset, total, 200)
