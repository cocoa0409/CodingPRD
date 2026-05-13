"""Credit notes routes."""
from flask import Blueprint, request, g

from db import store, new_id, now_iso
from errors import (
    raise_error,
    ERR_FORBIDDEN,
    ERR_INVALID_AMOUNT,
    ERR_INVOICE_NOT_FOUND,
    ERR_TENANT_READ_ONLY,
)
from middleware import authenticate, enforce_tenant_isolation
from response import success, parse_pagination, paginate
from routes.tenants import get_tenant_or_404
from services.audit import write_audit
from services.invoices import recompute_invoice_totals, recompute_tenant_outstanding


bp = Blueprint("credit_notes", __name__)


def _check_role(allowed):
    if g.actor_role not in allowed:
        raise_error(ERR_FORBIDDEN, "Not permitted")


@bp.route("/tenants/<tenant_id>/credit-notes", methods=["POST"])
def create_credit_note(tenant_id):
    authenticate()
    _check_role(("PlatformAdmin", "BillingOperator"))
    tenant = get_tenant_or_404(tenant_id)
    enforce_tenant_isolation(tenant_id)
    if tenant.get("restriction_level") in ("READ_ONLY", "FEATURE_RESTRICTED"):
        raise_error(ERR_TENANT_READ_ONLY, "Tenant is restricted")

    body = request.get_json(silent=True) or {}
    origin = body.get("origin")
    amount = body.get("amount_cents")
    applied_to = body.get("applied_to_invoice_id")
    try:
        amount_int = int(amount)
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_AMOUNT, "amount_cents must be a positive integer")
    if amount_int <= 0:
        raise_error(ERR_INVALID_AMOUNT, "amount_cents must be > 0")

    cn_id = new_id()
    cn = {
        "id": cn_id,
        "created_at": now_iso(),
        "tenant_id": tenant_id,
        "origin": origin,
        "amount_cents": amount_int,
        "applied_to_invoice_id": None,
        "applied_cents": 0,
    }
    store.credit_notes[cn_id] = cn

    if applied_to:
        inv = store.invoices.get(applied_to)
        if inv is None or inv["tenant_id"] != tenant_id:
            raise_error(ERR_INVOICE_NOT_FOUND, f"Invoice {applied_to} not found for tenant")
        cn["applied_to_invoice_id"] = applied_to
        # Apply as much as possible to invoice cap
        taxable_base = int(inv.get("subtotal_cents", 0)) - int(inv.get("discount_cents", 0))
        cap = max(taxable_base + int(inv.get("tax_cents", 0)), 0)
        already_applied = sum(int(c.get("applied_cents", 0)) for c in store.credit_notes.values()
                              if c.get("applied_to_invoice_id") == applied_to and c["id"] != cn_id)
        remaining_cap = max(cap - already_applied, 0)
        take = min(amount_int, remaining_cap)
        cn["applied_cents"] = take
        recompute_invoice_totals(inv, recompute_late_fee=False)
        inv["updated_at"] = now_iso()
        inv["version"] = int(inv.get("version", 1)) + 1
        recompute_tenant_outstanding(tenant)

    write_audit(tenant_id, "CREDIT_ISSUE", "CreditNote", cn_id, {}, dict(cn))
    return success(dict(cn), status=201)


@bp.route("/tenants/<tenant_id>/credit-notes", methods=["GET"])
def list_credit_notes(tenant_id):
    authenticate()
    _check_role(("PlatformAdmin", "BillingOperator", "TenantAdmin"))
    get_tenant_or_404(tenant_id)
    enforce_tenant_isolation(tenant_id)
    limit, offset = parse_pagination(request.args)
    items = [c for c in store.credit_notes.values() if c["tenant_id"] == tenant_id]
    items.sort(key=lambda c: c["created_at"])
    page, meta = paginate(items, limit, offset)
    return success([dict(c) for c in page], status=200, pagination=meta,
                   response_type="array")
