from datetime import timedelta
from flask import Blueprint, request, g

from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_BILL_STATE, ERR_EMPTY_BILL,
    ERR_BILL_HAS_OPEN_RESERVATIONS, ERR_FORBIDDEN,
)
from response import success
from middleware import require_roles
from util import bump, check_version, now_iso_string
from util_pagination import parse_pagination, paginate
from db import db
from services.bill_service import bill_view, recompute_bill_totals
from services.tenant_service import refresh_tenant

bp = Blueprint("bills", __name__)


@bp.route("/bills/<bill_id>/issue", methods=["POST"])
def issue_bill(bill_id):
    require_roles("BillingOfficer")
    b = db.bills.get(bill_id)
    if not b:
        raise_error(ERR_NOT_FOUND, "Bill not found")
    body = request.get_json(silent=True) or {}
    check_version(b, body.get("version"))
    if b["status"] != "DRAFT":
        raise_error(ERR_INVALID_BILL_STATE, "Bill is not DRAFT")

    # Subtotal must be strictly > 0 (equivalent to at least one BillLine)
    recompute_bill_totals(b)
    if b["subtotal_cents"] <= 0:
        raise_error(ERR_EMPTY_BILL, "Bill has no lines")

    # No reservations pointing here in PENDING/CONFIRMED/IN_USE
    for r in db.reservations.values():
        if r.get("bill_id") == bill_id and r["status"] in ("PENDING", "CONFIRMED", "IN_USE"):
            raise_error(ERR_BILL_HAS_OPEN_RESERVATIONS, "Bill has open reservations")

    now = db.now()
    b["status"] = "ISSUED"
    b["issued_at"] = now_iso_string(now)
    b["due_at"] = now_iso_string(now + timedelta(days=14))
    bump(b, now)

    # Recompute tenant outstanding + posture
    tenant = db.tenants.get(b["tenant_id"])
    if tenant:
        refresh_tenant(tenant)
        bump(tenant, now)

    return success(bill_view(b))


@bp.route("/bills/<bill_id>/pay", methods=["POST"])
def pay_bill(bill_id):
    require_roles("PaymentClerk")
    b = db.bills.get(bill_id)
    if not b:
        raise_error(ERR_NOT_FOUND, "Bill not found")
    body = request.get_json(silent=True) or {}
    check_version(b, body.get("version"))
    if b["status"] not in ("ISSUED", "OVERDUE"):
        raise_error(ERR_INVALID_BILL_STATE, "Bill must be ISSUED or OVERDUE to pay")
    now = db.now()
    b["status"] = "PAID"
    b["paid_at"] = now_iso_string(now)
    bump(b, now)

    tenant = db.tenants.get(b["tenant_id"])
    if tenant:
        refresh_tenant(tenant)
        bump(tenant, now)

    return success(bill_view(b))


@bp.route("/bills/<bill_id>/void", methods=["POST"])
def void_bill(bill_id):
    require_roles("PlatformAdmin")
    b = db.bills.get(bill_id)
    if not b:
        raise_error(ERR_NOT_FOUND, "Bill not found")
    body = request.get_json(silent=True) or {}
    check_version(b, body.get("version"))
    if b["status"] != "DRAFT":
        raise_error(ERR_INVALID_BILL_STATE, "Only DRAFT bills can be voided")
    now = db.now()
    b["status"] = "VOIDED"
    bump(b, now)

    # Cascade: clear bill_id on reservations and visitors
    for r in db.reservations.values():
        if r.get("bill_id") == bill_id:
            r["bill_id"] = None
            bump(r, now)
    for v in db.visitors.values():
        if v.get("bill_id") == bill_id:
            v["bill_id"] = None

    tenant = db.tenants.get(b["tenant_id"])
    if tenant:
        refresh_tenant(tenant)
        bump(tenant, now)

    return success(bill_view(b))


@bp.route("/bills/<bill_id>", methods=["GET"])
def get_bill(bill_id):
    require_roles("PlatformAdmin", "TenantAdmin", "BillingOfficer", "PaymentClerk")
    b = db.bills.get(bill_id)
    if not b:
        raise_error(ERR_NOT_FOUND, "Bill not found")
    if g.user_role == "TenantAdmin":
        actor = g.acting_member
        if not actor or actor["tenant_id"] != b["tenant_id"]:
            raise_error(ERR_FORBIDDEN, "Bill not accessible")
    return success(bill_view(b))


@bp.route("/bills", methods=["GET"])
def list_bills():
    require_roles("PlatformAdmin", "TenantAdmin", "BillingOfficer", "PaymentClerk")
    tenant_id = request.args.get("tenant_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()

    items = list(db.bills.values())
    if g.user_role == "TenantAdmin":
        actor = g.acting_member
        if not actor:
            raise_error(ERR_FORBIDDEN, "No acting tenant")
        items = [b for b in items if b["tenant_id"] == actor["tenant_id"]]
    if tenant_id:
        items = [b for b in items if b["tenant_id"] == tenant_id]
    if status:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda b: b["created_at"])
    page, meta = paginate(items, limit, offset)
    return success([bill_view(b) for b in page], pagination=meta)
