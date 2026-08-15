"""Tenant endpoints: create, get, and the logical clock advance (PRD §2.4)."""

from flask import Blueprint, request

import db
import services.domain as domain
from middleware import bump, require_role
from response import created, ok

bp = Blueprint("tenants", __name__)


@bp.route("/tenants", methods=["POST"])
def create_tenant():
    require_role("TenantAdmin")
    body = request.get_json(silent=True) or {}
    fields = {
        "legal_name": body.get("legal_name"),
        "home_state_code": body.get("home_state_code"),
        # PRD §3.5: coverage_mode pins one of the two coverage variants.
        "coverage_mode": body.get("coverage_mode") or "FULL_CERT",
        "audit_clock_day_index": 0,
        "audit_posture": "CLEAR",
        "open_exposure_cents": 0,
    }
    rec = db.make_record(fields)
    db.stores["tenants"][rec["id"]] = rec
    return created(db.pub(rec))


@bp.route("/tenants/<tid>", methods=["GET"])
def get_tenant(tid):
    require_role(
        "TenantAdmin", "ComplianceOfficer", "Auditor",
        "OrderClerk", "FulfillmentClerk", "BillingClerk",
    )
    tenant = domain.get_tenant(tid)
    return ok(db.pub(tenant))


@bp.route("/tenants/<tid>/_clock/advance_day", methods=["POST"])
def advance_day(tid):
    require_role("TenantAdmin")
    tenant = domain.get_tenant(tid)
    body = request.get_json(silent=True) or {}
    days = body.get("days", 1)
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 1
    tenant["audit_clock_day_index"] += days
    bump(tenant)
    domain.advance_day_cascades(tenant)
    return ok(db.pub(tenant))
