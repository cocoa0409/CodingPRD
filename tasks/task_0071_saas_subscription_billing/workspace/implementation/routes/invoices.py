"""Invoice routes."""
from flask import Blueprint, request, g

from clock import clock, iso
from datetime import timedelta

from db import store, now_iso, new_id
from errors import (
    raise_error,
    ERR_FORBIDDEN,
    ERR_INVOICE_NOT_FOUND,
    ERR_INVOICE_STATUS_INVALID,
    ERR_VERSION_CONFLICT,
    ERR_DISCOUNT_EXCEEDS_SUBTOTAL,
    ERR_INVALID_AMOUNT,
    ERR_CURRENCY_MISMATCH,
    ERR_DUPLICATE_PAYMENT_REFERENCE,
    ERR_TENANT_READ_ONLY,
    ERR_TENANT_STATUS_INVALID,
    ERR_INVOICE_CYCLE_ALREADY_ISSUED,
)
from middleware import authenticate, enforce_tenant_isolation
from response import success, parse_pagination, paginate
from routes.tenants import get_tenant_or_404
from services.audit import write_audit, emit_sync_event
from services.invoices import (
    recompute_invoice_totals,
    recompute_tenant_outstanding,
    apply_payment_cascade,
    DEFAULT_DUE_DAYS,
)


bp = Blueprint("invoices", __name__)


def _check_role(allowed):
    if g.actor_role not in allowed:
        raise_error(ERR_FORBIDDEN, "Not permitted")


def get_invoice_for_tenant(tenant_id, invoice_id):
    inv = store.invoices.get(invoice_id)
    if inv is None or inv["tenant_id"] != tenant_id:
        raise_error(ERR_INVOICE_NOT_FOUND, f"Invoice {invoice_id} not found")
    return inv


def serialize_invoice(inv):
    return dict(inv)


@bp.route("/tenants/<tenant_id>/invoices", methods=["GET"])
def list_invoices(tenant_id):
    authenticate()
    _check_role(("PlatformAdmin", "BillingOperator", "TenantAdmin"))
    get_tenant_or_404(tenant_id)
    enforce_tenant_isolation(tenant_id)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("invoice_status")
    items = [i for i in store.invoices.values() if i["tenant_id"] == tenant_id]
    if status:
        items = [i for i in items if i["invoice_status"] == status]
    items.sort(key=lambda i: i["created_at"])
    page, meta = paginate(items, limit, offset)
    return success([serialize_invoice(i) for i in page], status=200,
                   pagination=meta, response_type="array")


@bp.route("/tenants/<tenant_id>/invoices/<inv_id>", methods=["GET"])
def get_invoice(tenant_id, inv_id):
    authenticate()
    _check_role(("PlatformAdmin", "BillingOperator", "TenantAdmin"))
    get_tenant_or_404(tenant_id)
    enforce_tenant_isolation(tenant_id)
    inv = get_invoice_for_tenant(tenant_id, inv_id)
    return success(serialize_invoice(inv), status=200)


@bp.route("/tenants/<tenant_id>/invoices/<inv_id>", methods=["PATCH"])
def patch_invoice(tenant_id, inv_id):
    authenticate()
    _check_role(("PlatformAdmin", "BillingOperator"))
    tenant = get_tenant_or_404(tenant_id)
    enforce_tenant_isolation(tenant_id)
    inv = get_invoice_for_tenant(tenant_id, inv_id)
    if inv["invoice_status"] != "DRAFT":
        raise_error(ERR_INVOICE_STATUS_INVALID,
                    "Invoices can only be discounted while in DRAFT")
    if tenant.get("restriction_level") in ("READ_ONLY", "FEATURE_RESTRICTED"):
        raise_error(ERR_TENANT_READ_ONLY, "Tenant is restricted")

    body = request.get_json(silent=True) or {}
    if "version" in body and body["version"] is not None:
        if int(body["version"]) != int(inv["version"]):
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch")
    if "discount_cents" in body:
        try:
            disc = int(body["discount_cents"])
        except (TypeError, ValueError):
            raise_error(ERR_DISCOUNT_EXCEEDS_SUBTOTAL,
                        "discount_cents must be integer")
        if disc < 0 or disc > int(inv.get("subtotal_cents", 0)):
            raise_error(ERR_DISCOUNT_EXCEEDS_SUBTOTAL,
                        "discount_cents out of allowed range")
        before = dict(inv)
        inv["discount_cents"] = disc
        recompute_invoice_totals(inv, recompute_late_fee=False)
        inv["updated_at"] = now_iso()
        inv["version"] = int(inv["version"]) + 1
        write_audit(tenant_id, "INVOICE_ADJUSTMENT", "Invoice", inv_id,
                    {"discount_cents": before.get("discount_cents", 0)},
                    {"discount_cents": disc})
    return success(serialize_invoice(inv), status=200)


@bp.route("/tenants/<tenant_id>/invoices/<inv_id>/issue", methods=["POST"])
def issue_invoice(tenant_id, inv_id):
    authenticate()
    _check_role(("PlatformAdmin", "BillingOperator"))
    tenant = get_tenant_or_404(tenant_id)
    enforce_tenant_isolation(tenant_id)
    inv = get_invoice_for_tenant(tenant_id, inv_id)
    if inv["invoice_status"] != "DRAFT":
        raise_error(ERR_INVOICE_STATUS_INVALID,
                    "Only DRAFT invoices can be issued")
    if tenant.get("restriction_level") in ("READ_ONLY", "FEATURE_RESTRICTED"):
        raise_error(ERR_TENANT_READ_ONLY, "Tenant is restricted")

    body = request.get_json(silent=True) or {}
    if "version" in body and body["version"] is not None:
        if int(body["version"]) != int(inv["version"]):
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch")

    # Uniqueness on (subscription_id, cycle_start, pricing_model)
    for other in store.invoices.values():
        if other["id"] == inv_id:
            continue
        if (other["subscription_id"] == inv["subscription_id"]
                and other["cycle_start"] == inv["cycle_start"]
                and other["pricing_model"] == inv["pricing_model"]
                and other["invoice_status"] not in ("WRITTEN_OFF",)):
            raise_error(ERR_INVOICE_CYCLE_ALREADY_ISSUED,
                        "Invoice for this cycle already exists")

    recompute_invoice_totals(inv, recompute_late_fee=False)
    now = clock.now()
    inv["due_at"] = iso(now + timedelta(days=DEFAULT_DUE_DAYS))
    inv["invoice_status"] = "ISSUED"
    inv["updated_at"] = now_iso()
    inv["version"] = int(inv["version"]) + 1
    emit_sync_event(tenant_id, "ACCOUNTING", "INVOICE_ISSUED", dict(inv))
    recompute_tenant_outstanding(tenant)
    return success(serialize_invoice(inv), status=200)


@bp.route("/tenants/<tenant_id>/invoices/<inv_id>/payments", methods=["POST"])
def post_payment(tenant_id, inv_id):
    authenticate()
    _check_role(("PlatformAdmin", "BillingOperator", "TenantAdmin"))
    tenant = get_tenant_or_404(tenant_id)
    enforce_tenant_isolation(tenant_id)
    inv = get_invoice_for_tenant(tenant_id, inv_id)

    body = request.get_json(silent=True) or {}
    amount = body.get("amount_cents")
    currency = body.get("currency")
    ext_ref = body.get("external_reference")

    # Idempotency check FIRST per pure-idempotent-replay contract (§2.10).
    # An identical replay returns the originally persisted Payment with HTTP 201
    # regardless of subsequent invoice state changes.
    if ext_ref:
        existing = None
        for p in store.payments.values():
            if p["tenant_id"] == tenant_id and p["external_reference"] == ext_ref:
                existing = p
                break
        if existing is not None:
            try:
                amount_cmp = int(amount) if amount is not None else None
            except (TypeError, ValueError):
                amount_cmp = None
            same = (existing["invoice_id"] == inv_id
                    and amount_cmp is not None
                    and int(existing["amount_cents"]) == amount_cmp
                    and existing["currency"] == currency)
            if same:
                return success(dict(existing), status=201)
            raise_error(ERR_DUPLICATE_PAYMENT_REFERENCE,
                        "Duplicate external_reference with conflicting payload")

    # Payments are allowed even under restriction. Don't enforce restriction here.
    if inv["invoice_status"] not in ("ISSUED", "PARTIALLY_PAID", "OVERDUE"):
        raise_error(ERR_INVOICE_STATUS_INVALID,
                    f"Cannot pay invoice in status {inv['invoice_status']}")

    try:
        amount_int = int(amount)
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_AMOUNT, "amount_cents must be a positive integer")
    if amount_int <= 0:
        raise_error(ERR_INVALID_AMOUNT, "amount_cents must be > 0")
    if currency != inv["currency"]:
        raise_error(ERR_CURRENCY_MISMATCH,
                    "Payment currency must match invoice currency")

    pid = new_id()
    payment = {
        "id": pid,
        "created_at": now_iso(),
        "tenant_id": tenant_id,
        "invoice_id": inv_id,
        "amount_cents": amount_int,
        "currency": currency,
        "external_reference": ext_ref,
        "payment_status": "RECEIVED",
    }
    store.payments[pid] = payment

    apply_payment_cascade(inv, payment)
    return success(dict(payment), status=201)
