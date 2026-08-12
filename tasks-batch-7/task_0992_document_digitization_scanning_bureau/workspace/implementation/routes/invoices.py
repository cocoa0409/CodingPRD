"""Invoices: get, issue, payments, void."""

from flask import Blueprint

from db import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_PAYMENT_EXCEEDS_BALANCE,
    ERR_INVOICE_NOT_ISSUED,
    ERR_CLIENT_SUSPENDED,
)
from middleware import require_roles, check_client_user_scope
from response import success_object
from util import get_body, require_fields, reject_unknown, as_int, as_str, bump, now_iso
from services.serializers import invoice_view, get_agreement_for_client
from services.pricing import page_subtotal_cents, storage_fee_total

bp = Blueprint("invoices", __name__)


def get_invoice_or_404(invoice_id):
    inv = db.invoices.get(invoice_id)
    if not inv:
        raise ApiError(ERR_NOT_FOUND, "Invoice not found", 404)
    return inv


def check_client_active(inv):
    client = db.clients.get(inv["client_id"])
    if client and client["status"] == "SUSPENDED":
        raise ApiError(ERR_CLIENT_SUSPENDED, "Client is suspended", 403)


def _refresh_draft(inv):
    """Persist recomputed subtotals on a DRAFT invoice (also done on read view)."""
    if inv["status"] != "DRAFT":
        return
    batch = db.batches.get(inv["batch_id"])
    agreement = get_agreement_for_client(inv["client_id"])
    if not batch or not agreement:
        return
    page_sub = page_subtotal_cents(batch, agreement)
    storage_sub = storage_fee_total(batch, agreement, db.current_utc)
    if (
        inv["page_subtotal_cents"] != page_sub
        or inv["storage_subtotal_cents"] != storage_sub
    ):
        inv["page_subtotal_cents"] = page_sub
        inv["storage_subtotal_cents"] = storage_sub
        inv["total_cents"] = page_sub + storage_sub
        bump(inv)


@bp.route("/invoices/<id>", methods=["GET"])
@require_roles("PlatformAdmin", "BillingClerk", "ClientUser")
def get_invoice(id, _user_id, _role):
    inv = get_invoice_or_404(id)
    check_client_user_scope(_user_id, _role, inv["client_id"])
    _refresh_draft(inv)
    return success_object(invoice_view(inv, recompute=False))


@bp.route("/invoices/<id>/issue", methods=["POST"])
@require_roles("BillingClerk")
def issue_invoice(id, _user_id, _role):
    inv = get_invoice_or_404(id)
    get_body()
    check_client_active(inv)
    if inv["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Invoice is not DRAFT", 409)
    batch = db.batches.get(inv["batch_id"])
    if not batch or batch["status"] not in ("DELIVERED", "DISPOSITION_PENDING", "CLOSED"):
        raise ApiError(
            ERR_INVALID_STATE, "Batch must be DELIVERED, DISPOSITION_PENDING, or CLOSED", 409
        )
    agreement = get_agreement_for_client(inv["client_id"])
    page_sub = page_subtotal_cents(batch, agreement) if agreement else inv["page_subtotal_cents"]
    storage_sub = (
        storage_fee_total(batch, agreement, db.current_utc)
        if agreement
        else inv["storage_subtotal_cents"]
    )
    inv["page_subtotal_cents"] = page_sub
    inv["storage_subtotal_cents"] = storage_sub
    inv["total_cents"] = page_sub + storage_sub
    inv["issued_at"] = now_iso()
    inv["status"] = "ISSUED"
    bump(inv)
    return success_object(invoice_view(inv, recompute=False))


@bp.route("/invoices/<id>/payments", methods=["POST"])
@require_roles("BillingClerk")
def capture_payment(id, _user_id, _role):
    inv = get_invoice_or_404(id)
    body = get_body()
    require_fields(body, ["amount_cents"])
    reject_unknown(body, {"amount_cents"})
    amount = as_int(body["amount_cents"], "amount_cents", minimum=1)
    check_client_active(inv)
    if inv["status"] in ("DRAFT", "VOID"):
        raise ApiError(ERR_INVOICE_NOT_ISSUED, "Invoice is not in a payable state", 409)
    outstanding = inv["total_cents"] - inv["amount_paid_cents"]
    if amount > outstanding:
        raise ApiError(ERR_PAYMENT_EXCEEDS_BALANCE, "Payment exceeds outstanding balance", 422)
    inv["amount_paid_cents"] += amount
    if inv["amount_paid_cents"] == inv["total_cents"]:
        inv["status"] = "PAID"
    else:
        inv["status"] = "PARTIALLY_PAID"
    bump(inv)
    return success_object(invoice_view(inv, recompute=False))


@bp.route("/invoices/<id>/void", methods=["POST"])
@require_roles("BillingClerk")
def void_invoice(id, _user_id, _role):
    inv = get_invoice_or_404(id)
    body = get_body()
    require_fields(body, ["void_reason"])
    reject_unknown(body, {"void_reason"})
    reason = as_str(body["void_reason"], "void_reason")
    check_client_active(inv)
    if inv["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Invoice is not DRAFT", 409)
    inv["status"] = "VOID"
    inv["void_reason"] = reason
    bump(inv)
    return success_object(invoice_view(inv, recompute=False))
