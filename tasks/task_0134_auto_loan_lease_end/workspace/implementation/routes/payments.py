"""Payment endpoints — PRD §3.5."""
from __future__ import annotations

from flask import Blueprint, g, request

from config import (
    ROLE_COLLECTIONS_AGENT,
    ROLE_CUSTOMER,
    ROLE_FINANCE_MANAGER,
    ROLE_LOAN_OFFICER,
)
from db import store
from errors import (
    err_customer_not_found,
    err_invalid_request,
    err_payment_not_payable,
)
from middleware import is_customer, require_auth
from response import list_success, success
from routes._helpers import (
    get_json,
    paginate,
    parse_pagination,
    sort_by_created_at,
)
from services.engine import (
    apply_payment_paid,
    get_customer_or_404,
    get_payment_or_404,
)
from services.serializers import serialize_payment

bp = Blueprint("payments", __name__)


def _check_customer_ownership(customer_id: str):
    if is_customer() and g.user_id != customer_id:
        raise err_customer_not_found()


_PAYMENT_STATUSES = {"SCHEDULED", "PAID", "LATE", "DEFAULTED"}


# ── GET /customers/{customerId}/payments ───────────────────────────────────


@bp.get("/customers/<customer_id>/payments")
@require_auth([ROLE_LOAN_OFFICER, ROLE_FINANCE_MANAGER, ROLE_COLLECTIONS_AGENT, ROLE_CUSTOMER])
def list_payments(customer_id):
    customer = get_customer_or_404(customer_id)
    _check_customer_ownership(customer_id)
    limit, offset = parse_pagination()

    contract_id = request.args.get("contract_id")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in _PAYMENT_STATUSES:
        raise err_invalid_request(f"status must be one of {sorted(_PAYMENT_STATUSES)}.")

    items = [p for p in store.payments.values() if p["customer_id"] == customer_id]
    if contract_id is not None:
        items = [p for p in items if p["contract_id"] == contract_id]
    if status_filter is not None:
        items = [p for p in items if p["status"] == status_filter]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([serialize_payment(p) for p in page], limit, offset, total)


# ── GET /customers/{customerId}/payments/{paymentId} ───────────────────────


@bp.get("/customers/<customer_id>/payments/<payment_id>")
@require_auth([ROLE_LOAN_OFFICER, ROLE_FINANCE_MANAGER, ROLE_COLLECTIONS_AGENT, ROLE_CUSTOMER])
def get_payment(customer_id, payment_id):
    customer = get_customer_or_404(customer_id)
    _check_customer_ownership(customer_id)
    p = get_payment_or_404(customer_id, payment_id)
    return success(serialize_payment(p))


# ── POST /customers/{customerId}/payments/{paymentId}/pay ──────────────────


@bp.post("/customers/<customer_id>/payments/<payment_id>/pay")
@require_auth([ROLE_CUSTOMER])
def pay_payment(customer_id, payment_id):
    customer = get_customer_or_404(customer_id)
    _check_customer_ownership(customer_id)
    payment = get_payment_or_404(customer_id, payment_id)

    if payment["status"] not in {"SCHEDULED", "LATE", "DEFAULTED"}:
        raise err_payment_not_payable(
            f"Payment is in {payment['status']}; cannot pay."
        )

    # Determine parent contract state.
    if payment["contract_type"] == "LOAN":
        parent = store.loan_contracts.get(payment["contract_id"])
    else:
        parent = store.lease_contracts.get(payment["contract_id"])
    if parent is None:
        raise err_payment_not_payable("Parent contract not found.")

    parent_status = parent["status"]
    if payment["status"] in {"SCHEDULED", "LATE"}:
        if parent_status not in {"ACTIVE", "DEFAULTED"}:
            raise err_payment_not_payable(
                f"Parent contract is in {parent_status}; payment is not payable."
            )
    else:  # DEFAULTED
        if parent_status != "DEFAULTED":
            raise err_payment_not_payable(
                f"Defaulted payment can only be paid when parent contract is DEFAULTED."
            )

    with store.lock:
        apply_payment_paid(payment)
    return success(serialize_payment(payment))
