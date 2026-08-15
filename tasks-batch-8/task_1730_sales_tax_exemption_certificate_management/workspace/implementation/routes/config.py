"""JurisdictionRule and ExemptionReason endpoints (PRD §3.1)."""

from flask import Blueprint, request

import db
import services.domain as domain
from middleware import require_role
from response import created, ok_list
from errors import ApiError

bp = Blueprint("config", __name__)


# --- JurisdictionRule -------------------------------------------------------

@bp.route("/tenants/<tid>/jurisdiction_rules", methods=["POST"])
def create_rule(tid):
    require_role("TenantAdmin")
    tenant = domain.get_tenant(tid)
    body = request.get_json(silent=True) or {}
    # Priority 27: one rule per state per tenant.
    if domain.find_rule(tenant["id"], body.get("state_code")):
        raise ApiError(
            "ERR_DUPLICATE_JURISDICTION",
            "A JurisdictionRule for this state_code already exists for the tenant",
            409,
        )
    rec = db.make_record({
        "tenant_id": tenant["id"],
        "state_code": body.get("state_code"),
        "accepted_form_types": body.get("accepted_form_types") or [],
        "validity_window_days": body.get("validity_window_days"),
        "anchor_rule": body.get("anchor_rule"),
        "allows_drop_ship_resale": body.get("allows_drop_ship_resale"),
        "requires_state_registration_number": body.get("requires_state_registration_number"),
        "blanket_cert_allowed": body.get("blanket_cert_allowed"),
    })
    db.stores["jurisdiction_rules"][rec["id"]] = rec
    return created(db.pub(rec))


@bp.route("/tenants/<tid>/jurisdiction_rules", methods=["GET"])
def list_rules(tid):
    require_role("TenantAdmin", "ComplianceOfficer", "Auditor")
    tenant = domain.get_tenant(tid)
    state_code = request.args.get("state_code")
    items = [r for r in db.stores["jurisdiction_rules"].values() if r["tenant_id"] == tenant["id"]]
    if state_code is not None:
        items = [r for r in items if r["state_code"] == state_code]
    items.sort(key=lambda r: r["_seq"])
    return ok_list([db.pub(r) for r in items])


@bp.route("/tenants/<tid>/jurisdiction_rules/<rid>", methods=["GET"])
def get_rule(tid, rid):
    require_role("TenantAdmin", "ComplianceOfficer", "Auditor")
    tenant = domain.get_tenant(tid)
    rec = domain.get_scoped("jurisdiction_rules", rid, tenant["id"])
    return ok(rec and db.pub(rec))


# --- ExemptionReason --------------------------------------------------------

@bp.route("/tenants/<tid>/exemption_reasons", methods=["POST"])
def create_reason(tid):
    require_role("TenantAdmin")
    tenant = domain.get_tenant(tid)
    body = request.get_json(silent=True) or {}
    # Priority 26: reason code unique within tenant.
    if domain.find_reason(tenant["id"], body.get("code")):
        raise ApiError(
            "ERR_DUPLICATE_REASON_CODE",
            "An ExemptionReason with this code already exists for the tenant",
            409,
        )
    rec = db.make_record({
        "tenant_id": tenant["id"],
        "code": body.get("code"),
        "description": body.get("description"),
        "tax_engine_code": body.get("tax_engine_code"),
        "requires_certificate": body.get("requires_certificate"),
        "allowed_form_types": body.get("allowed_form_types") or [],
    })
    db.stores["exemption_reasons"][rec["id"]] = rec
    return created(db.pub(rec))


@bp.route("/tenants/<tid>/exemption_reasons", methods=["GET"])
def list_reasons(tid):
    require_role("TenantAdmin", "ComplianceOfficer", "Auditor", "OrderClerk")
    tenant = domain.get_tenant(tid)
    code = request.args.get("code")
    items = [r for r in db.stores["exemption_reasons"].values() if r["tenant_id"] == tenant["id"]]
    if code is not None:
        items = [r for r in items if r["code"] == code]
    items.sort(key=lambda r: r["_seq"])
    return ok_list([db.pub(r) for r in items])
