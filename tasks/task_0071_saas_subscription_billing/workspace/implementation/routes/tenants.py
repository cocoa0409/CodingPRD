"""Tenant routes."""
from flask import Blueprint, request, g

from clock import clock, iso, parse_iso

from db import store, new_id, now_iso
from errors import (
    raise_error,
    ERR_TENANT_NOT_FOUND,
    ERR_TENANT_STATUS_INVALID,
    ERR_VERSION_CONFLICT,
    ERR_INVALID_PARENT_TENANT,
    ERR_JURISDICTION_NOT_FOUND,
    ERR_OUTSTANDING_BALANCE_EXISTS,
    ERR_TENANT_HAS_SUBSIDIARIES,
    ERR_TENANT_READ_ONLY,
)
from middleware import authenticate, require_roles, enforce_tenant_isolation
from response import success, parse_pagination, paginate
from services.audit import write_audit, emit_sync_event
from services.invoices import recompute_tenant_outstanding


bp = Blueprint("tenants", __name__)


def serialize_tenant(t):
    return dict(t)


def get_tenant_or_404(tid):
    t = store.tenants.get(tid)
    if t is None:
        raise_error(ERR_TENANT_NOT_FOUND, f"Tenant {tid} not found")
    return t


@bp.route("/tenants", methods=["POST"])
@require_roles("PlatformAdmin")
def create_tenant():
    body = request.get_json(silent=True) or {}
    legal_name = body.get("legal_name")
    contact_email = body.get("contact_email")
    contact_phone = body.get("contact_phone")
    billing_entity_type = body.get("billing_entity_type")
    parent_tenant_id = body.get("parent_tenant_id")
    currency = body.get("currency")
    jurisdiction_code = body.get("jurisdiction_code")
    trial_expires_at = body.get("trial_expires_at")

    # Jurisdiction must exist
    juris = store.jurisdiction_by_code(jurisdiction_code) if jurisdiction_code else None
    if juris is None:
        raise_error(ERR_JURISDICTION_NOT_FOUND,
                    f"Jurisdiction {jurisdiction_code} not registered")

    # Parent tenant validation for SUBSIDIARY
    if billing_entity_type == "SUBSIDIARY":
        if not parent_tenant_id:
            raise_error(ERR_INVALID_PARENT_TENANT,
                        "parent_tenant_id required when billing_entity_type=SUBSIDIARY")
        parent = store.tenants.get(parent_tenant_id)
        if parent is None or parent.get("billing_entity_type") != "PARENT":
            raise_error(ERR_INVALID_PARENT_TENANT,
                        "parent_tenant_id must refer to a PARENT tenant")
    else:
        parent_tenant_id = None

    tid = new_id()
    created = now_iso()
    tenant = {
        "id": tid,
        "created_at": created,
        "updated_at": created,
        "version": 1,
        "legal_name": legal_name,
        "contact_email": contact_email,
        "contact_phone": contact_phone,
        "billing_entity_type": billing_entity_type,
        "parent_tenant_id": parent_tenant_id,
        "currency": currency,
        "jurisdiction_code": jurisdiction_code,
        "tenant_status": "TRIAL",
        "restriction_level": "NONE",
        "trial_expires_at": trial_expires_at,
        "outstanding_balance_cents": 0,
        "active_subscription_id": None,
    }
    store.tenants[tid] = tenant
    # Audit + Sync event placeholder to CRM
    write_audit(tid, "TENANT_STATUS_CHANGE", "Tenant", tid,
                {}, {"tenant_status": "TRIAL"})
    emit_sync_event(tid, "CRM", "SUBSCRIPTION_CREATED", dict(tenant))
    return success(serialize_tenant(tenant), status=201)


@bp.route("/tenants", methods=["GET"])
@require_roles("PlatformAdmin")
def list_tenants():
    limit, offset = parse_pagination(request.args)
    status_filter = request.args.get("tenant_status")
    items = list(store.tenants.values())
    if status_filter:
        items = [t for t in items if t["tenant_status"] == status_filter]
    items.sort(key=lambda t: t["created_at"])
    # Recompute computed fields
    for t in items:
        recompute_tenant_outstanding(t)
    page, meta = paginate(items, limit, offset)
    return success([serialize_tenant(t) for t in page], status=200, pagination=meta,
                   response_type="array")


@bp.route("/tenants/<tid>", methods=["GET"])
def get_tenant(tid):
    authenticate()
    role = g.actor_role
    if role not in ("PlatformAdmin", "BillingOperator", "TenantAdmin"):
        from errors import ERR_FORBIDDEN
        raise_error(ERR_FORBIDDEN, "Not permitted")
    tenant = get_tenant_or_404(tid)
    enforce_tenant_isolation(tid)
    recompute_tenant_outstanding(tenant)
    return success(serialize_tenant(tenant), status=200)


@bp.route("/tenants/<tid>", methods=["PATCH"])
def patch_tenant(tid):
    authenticate()
    role = g.actor_role
    if role not in ("PlatformAdmin", "TenantAdmin"):
        from errors import ERR_FORBIDDEN
        raise_error(ERR_FORBIDDEN, "Not permitted")
    tenant = get_tenant_or_404(tid)
    enforce_tenant_isolation(tid)
    # Restriction gating: only payments are allowed when READ_ONLY/FEATURE_RESTRICTED
    if tenant["tenant_status"] == "ACTIVE" and tenant["restriction_level"] in ("READ_ONLY", "FEATURE_RESTRICTED"):
        raise_error(ERR_TENANT_READ_ONLY, "Tenant is in restricted state")
    body = request.get_json(silent=True) or {}
    if "version" in body and body["version"] is not None:
        if int(body["version"]) != int(tenant["version"]):
            raise_error(ERR_VERSION_CONFLICT,
                        "Supplied version does not match stored version")
    before = dict(tenant)
    changed = False
    for field in ("legal_name", "contact_email", "contact_phone"):
        if field in body and body[field] is not None:
            tenant[field] = body[field]
            changed = True
    if changed:
        tenant["updated_at"] = now_iso()
        tenant["version"] = int(tenant["version"]) + 1
        write_audit(tid, "TENANT_STATUS_CHANGE", "Tenant", tid,
                    {"legal_name": before.get("legal_name"),
                     "contact_email": before.get("contact_email"),
                     "contact_phone": before.get("contact_phone")},
                    {"legal_name": tenant["legal_name"],
                     "contact_email": tenant["contact_email"],
                     "contact_phone": tenant["contact_phone"]})
    recompute_tenant_outstanding(tenant)
    return success(serialize_tenant(tenant), status=200)


@bp.route("/tenants/<tid>", methods=["DELETE"])
@require_roles("PlatformAdmin")
def delete_tenant(tid):
    tenant = get_tenant_or_404(tid)
    if tenant["tenant_status"] != "ACTIVE":
        # The state machine only models ACTIVE -> TERMINATED for explicit
        # DELETE. TRIAL/SUSPENDED tenants cannot be explicitly terminated.
        raise_error(ERR_TENANT_STATUS_INVALID,
                    f"Cannot terminate tenant in status {tenant['tenant_status']}")
    recompute_tenant_outstanding(tenant)
    if int(tenant["outstanding_balance_cents"]) > 0:
        raise_error(ERR_OUTSTANDING_BALANCE_EXISTS,
                    "Cannot terminate tenant with outstanding balance")
    if tenant.get("billing_entity_type") == "PARENT":
        for t in store.tenants.values():
            if t.get("parent_tenant_id") == tid and t["tenant_status"] != "TERMINATED":
                raise_error(ERR_TENANT_HAS_SUBSIDIARIES,
                            "Cannot terminate PARENT with attached subsidiaries")
    before = {"tenant_status": tenant["tenant_status"]}
    tenant["tenant_status"] = "TERMINATED"
    tenant["updated_at"] = now_iso()
    tenant["version"] = int(tenant["version"]) + 1
    # Cancel active subscription
    for sub in store.subscriptions.values():
        if sub["tenant_id"] != tid:
            continue
        if sub["subscription_status"] in ("ACTIVE", "PENDING_DOWNGRADE", "TRIAL", "PENDING"):
            sub["subscription_status"] = "CANCELLED"
            sub["updated_at"] = now_iso()
            sub["version"] = int(sub.get("version", 1)) + 1
    write_audit(tid, "TENANT_STATUS_CHANGE", "Tenant", tid, before,
                {"tenant_status": "TERMINATED"})
    emit_sync_event(tid, "ACCOUNTING", "SUBSCRIPTION_CHANGED", dict(tenant))
    return ("", 204)
