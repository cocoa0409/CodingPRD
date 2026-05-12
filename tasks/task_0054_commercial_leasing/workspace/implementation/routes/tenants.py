"""Tenant routes."""
from flask import Blueprint, request, g

import db
from errors import err
from clock import now, parse_iso, to_utc_midnight, iso
from middleware import require_auth
from response import success
from services.lookups import get_tenant
from services.validation import require_body, require_str, require_iso
from services.tenant_ledger import recompute_for_tenant


bp = Blueprint("tenants", __name__)


def _tenant_public(t: dict) -> dict:
    recompute_for_tenant(t["id"])
    return db.public(t)


@bp.post("/tenants")
@require_auth(roles={"LeasingAgent"})
def create_tenant():
    body = require_body(request)
    legal_name = require_str(body, "legal_name")
    license_no = require_str(body, "business_license_no")
    license_expires = require_iso(body, "license_expires_on")
    contact_email = require_str(body, "contact_email")

    t = {
        "legal_name": legal_name,
        "business_license_no": license_no,
        "license_expires_on": iso(license_expires),
        "qualification_status": "PENDING_REVIEW",
        "contact_email": contact_email,
        "total_deposit_paid_cents": 0,
        "total_deposit_refunded_cents": 0,
        "total_deposit_retained_cents": 0,
    }
    db.stamp_create(t)
    db.tenants[t["id"]] = t
    return success(_tenant_public(t), status=201)


@bp.post("/tenants/<tenant_id>/approve")
@require_auth(roles={"LeasingAgent"})
def approve_tenant(tenant_id):
    t = get_tenant(tenant_id)
    if t["qualification_status"] != "PENDING_REVIEW":
        raise err("ERR_INVALID_STATE", f"Tenant must be PENDING_REVIEW (current: {t['qualification_status']})")
    # License check
    expires = parse_iso(t["license_expires_on"])
    today = to_utc_midnight(now())
    if expires <= today:
        raise err("ERR_LICENSE_EXPIRED", "Business license has expired")
    # Duplicate license check
    for other in db.tenants.values():
        if other["id"] == t["id"]:
            continue
        if other.get("qualification_status") == "REJECTED":
            continue
        if other.get("business_license_no") == t["business_license_no"]:
            raise err("ERR_DUPLICATE_LICENSE",
                      "Another tenant exists with this business_license_no")
    t["qualification_status"] = "APPROVED"
    db.stamp_update(t)
    return success(_tenant_public(t))


@bp.post("/tenants/<tenant_id>/reject")
@require_auth(roles={"LeasingAgent"})
def reject_tenant(tenant_id):
    t = get_tenant(tenant_id)
    if t["qualification_status"] != "PENDING_REVIEW":
        raise err("ERR_INVALID_STATE", f"Tenant must be PENDING_REVIEW (current: {t['qualification_status']})")
    t["qualification_status"] = "REJECTED"
    db.stamp_update(t)
    return success(_tenant_public(t))


@bp.post("/tenants/<tenant_id>/revoke-approval")
@require_auth(roles={"LeasingAgent"})
def revoke_approval(tenant_id):
    t = get_tenant(tenant_id)
    if t["qualification_status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", f"Tenant must be APPROVED (current: {t['qualification_status']})")
    # Blocked if active lease
    active_states = {"DRAFT", "SIGNED", "ACTIVE", "AMENDMENT_PENDING", "TERMINATING"}
    for le in db.leases.values():
        if le.get("tenant_id") == tenant_id and le.get("status") in active_states:
            raise err("ERR_TENANT_HAS_ACTIVE_LEASE",
                      "Cannot revoke approval — tenant has an active lease")
    t["qualification_status"] = "PENDING_REVIEW"
    db.stamp_update(t)
    return success(_tenant_public(t))


@bp.get("/tenants/<tenant_id>")
@require_auth(roles={"LeasingAgent", "FinanceOfficer", "Tenant"})
def get_tenant_route(tenant_id):
    t = get_tenant(tenant_id)
    if g.user_role == "Tenant" and g.user_id != tenant_id:
        raise err("ERR_FORBIDDEN", "Tenants can only view their own record")
    return success(_tenant_public(t))
