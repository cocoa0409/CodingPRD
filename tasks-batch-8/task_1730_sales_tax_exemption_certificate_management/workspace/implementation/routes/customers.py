"""Customer endpoints (PRD §3.2)."""

from flask import Blueprint, request

import db
import services.domain as domain
from middleware import bump, require_role
from response import created, ok, ok_list

bp = Blueprint("customers", __name__)


@bp.route("/tenants/<tid>/customers", methods=["POST"])
def create_customer(tid):
    require_role("TenantAdmin", "ComplianceOfficer")
    tenant = domain.get_tenant(tid)
    body = request.get_json(silent=True) or {}
    # Priority 4: body FK must resolve within the tenant.
    domain.require_reason(tenant["id"], body.get("exemption_reason_code"))
    rec = db.make_record({
        "tenant_id": tenant["id"],
        "external_ref": body.get("external_ref"),
        "legal_name": body.get("legal_name"),
        "primary_ship_to_state": body.get("primary_ship_to_state"),
        "exemption_reason_code": body.get("exemption_reason_code"),
        "cert_standing": "MISSING",
        "audit_standing": "NOT_UNDER_AUDIT",
        "collection_standing": "CURRENT",
        "onboarding_completed_at": None,
        "blocked_exposure_cents": 0,
    })
    db.stores["customers"][rec["id"]] = rec
    return created(db.pub(rec))


@bp.route("/tenants/<tid>/customers", methods=["GET"])
def list_customers(tid):
    require_role("TenantAdmin", "ComplianceOfficer", "Auditor", "OrderClerk")
    tenant = domain.get_tenant(tid)
    items = [c for c in db.stores["customers"].values() if c["tenant_id"] == tenant["id"]]
    for param in ("cert_standing", "collection_standing", "audit_standing"):
        val = request.args.get(param)
        if val is not None:
            items = [c for c in items if c[param] == val]
    items.sort(key=lambda c: c["_seq"])
    return ok_list([db.pub(c) for c in items])


@bp.route("/tenants/<tid>/customers/<cid>", methods=["GET"])
def get_customer(tid, cid):
    require_role(
        "TenantAdmin", "ComplianceOfficer", "Auditor",
        "OrderClerk", "FulfillmentClerk", "BillingClerk",
    )
    tenant = domain.get_tenant(tid)
    cust = domain.get_scoped("customers", cid, tenant["id"])
    return ok(db.pub(cust))


@bp.route("/tenants/<tid>/customers/<cid>/complete_onboarding", methods=["POST"])
def complete_onboarding(tid, cid):
    require_role("ComplianceOfficer")
    tenant = domain.get_tenant(tid)
    cust = domain.get_scoped("customers", cid, tenant["id"])
    cust["onboarding_completed_at"] = db.now_iso()
    bump(cust)
    return ok(db.pub(cust))
