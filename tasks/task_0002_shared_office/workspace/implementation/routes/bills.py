"""Bill routes."""
from datetime import timedelta

from flask import Blueprint, request

from clock import get_now, format_iso
from common import stamp_update, get_json_body, check_version, paginate
from db import db
from errors import api_error
from middleware import require_roles
from response import success
from services.bill import bill_to_public
from services.tenant import recompute_tenant

bp = Blueprint("bills", __name__)


@bp.route("/bills/<bill_id>", methods=["GET"])
def get_bill(bill_id):
    require_roles(["PlatformAdmin", "TenantAdmin", "BillingOfficer", "PaymentClerk"])
    bill = db.bills.get(bill_id)
    if not bill:
        raise api_error("ERR_NOT_FOUND", "bill not found")
    return success(bill_to_public(bill))


@bp.route("/bills", methods=["GET"])
def list_bills():
    require_roles(["PlatformAdmin", "TenantAdmin", "BillingOfficer", "PaymentClerk"])
    items = list(db.bills.values())
    tenant_id = request.args.get("tenant_id")
    status = request.args.get("status")
    if tenant_id:
        items = [b for b in items if b["tenant_id"] == tenant_id]
    if status:
        items = [b for b in items if b["status"] == status]
    page, meta = paginate(items)
    # Attach lines[] for each
    out = [bill_to_public(b) for b in page]
    return success(out, response_type="array", pagination=meta)


@bp.route("/bills/<bill_id>/issue", methods=["POST"])
def issue_bill(bill_id):
    require_roles(["BillingOfficer"])
    bill = db.bills.get(bill_id)
    if not bill:
        raise api_error("ERR_NOT_FOUND", "bill not found")
    body = get_json_body()
    check_version(bill, body)
    if bill["status"] != "DRAFT":
        raise api_error("ERR_INVALID_BILL_STATE", "bill not DRAFT")

    # At least one line
    lines = [l for l in db.bill_lines.values() if l["bill_id"] == bill_id]
    if not lines or bill.get("subtotal_cents", 0) <= 0:
        raise api_error("ERR_EMPTY_BILL", "bill has no lines")

    # All reservations pointing at this bill are COMPLETED or NO_SHOW
    for r in db.reservations.values():
        if r.get("bill_id") == bill_id and r["status"] not in ("COMPLETED", "NO_SHOW"):
            raise api_error("ERR_BILL_HAS_OPEN_RESERVATIONS", "bill has open reservations")

    now = get_now()
    bill["status"] = "ISSUED"
    bill["issued_at"] = format_iso(now)
    bill["due_at"] = format_iso(now + timedelta(days=14))
    stamp_update(bill)

    recompute_tenant(bill["tenant_id"])
    return success(bill_to_public(bill))


@bp.route("/bills/<bill_id>/pay", methods=["POST"])
def pay_bill(bill_id):
    require_roles(["PaymentClerk"])
    bill = db.bills.get(bill_id)
    if not bill:
        raise api_error("ERR_NOT_FOUND", "bill not found")
    body = get_json_body()
    check_version(bill, body)
    if bill["status"] not in ("ISSUED", "OVERDUE"):
        raise api_error("ERR_INVALID_BILL_STATE", "bill not ISSUED/OVERDUE")

    bill["status"] = "PAID"
    bill["paid_at"] = format_iso(get_now())
    stamp_update(bill)
    recompute_tenant(bill["tenant_id"])
    return success(bill_to_public(bill))


@bp.route("/bills/<bill_id>/void", methods=["POST"])
def void_bill(bill_id):
    require_roles(["PlatformAdmin"])
    bill = db.bills.get(bill_id)
    if not bill:
        raise api_error("ERR_NOT_FOUND", "bill not found")
    body = get_json_body()
    check_version(bill, body)
    if bill["status"] != "DRAFT":
        raise api_error("ERR_INVALID_BILL_STATE", "bill not DRAFT")

    bill["status"] = "VOIDED"
    stamp_update(bill)

    # Clear bill_id on Reservations and Visitors
    for r in db.reservations.values():
        if r.get("bill_id") == bill_id:
            r["bill_id"] = None
            stamp_update(r)
    for v in db.visitors.values():
        if v.get("bill_id") == bill_id:
            v["bill_id"] = None
    return success(bill_to_public(bill))
