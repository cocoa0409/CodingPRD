"""Customer account endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles, get_auth
from response import success_object, success_list
from services.helpers import (
    get_pagination, paginate, touch, require_fields, get_str, get_bool,
    check_customer_ownership,
)
from services.serializers import customer_view, quote_view, order_view, safety_audit_view

bp = Blueprint("customers", __name__)


@bp.route("/api/v1/customers", methods=["POST"])
def create_customer():
    require_roles("QuoteAgent", "PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, "company_name", "contact_email", "contact_phone", "billing_address")
    company_name = get_str(payload, "company_name", required=True)
    contact_email = get_str(payload, "contact_email", required=True)
    contact_phone = get_str(payload, "contact_phone", required=True)
    billing_address = get_str(payload, "billing_address", required=True)
    tax_exempt = get_bool(payload, "tax_exempt", default=False)

    now = db.iso_now()
    cid = db.new_id()
    c = {
        "id": cid,
        "company_name": company_name,
        "contact_email": contact_email,
        "contact_phone": contact_phone,
        "billing_address": billing_address,
        "tax_exempt": tax_exempt,
        "credit_status": "ACTIVE",
        "safety_audit_score": 100.0,
        "total_completed_trips": 0,
        "lifetime_revenue_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.customers[cid] = c
    return success_object(customer_view(c), status=201)


@bp.route("/api/v1/customers", methods=["GET"])
def list_customers():
    require_roles("QuoteAgent", "DispatchManager", "PlatformAdmin", "SafetyOfficer")
    limit, offset = get_pagination()
    credit_status = request.args.get("credit_status")
    items = sorted(db.customers.values(), key=lambda x: x["created_at"])
    if credit_status:
        items = [c for c in items if c.get("credit_status") == credit_status]
    page, total = paginate(items, limit, offset)
    return success_list([customer_view(c) for c in page], limit, offset, total)


@bp.route("/api/v1/customers/<cid>", methods=["GET"])
def get_customer(cid):
    user_id, role = require_roles("QuoteAgent", "DispatchManager", "PlatformAdmin", "Customer")
    c = db.customers.get(cid)
    if c is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "customer not found")
    if role == "Customer" and user_id != cid:
        raise errors.make_error(errors.ERR_UNAUTHORIZED, "Customer may only access own resources")
    return success_object(customer_view(c))


@bp.route("/api/v1/customers/<cid>", methods=["PATCH"])
def update_customer(cid):
    require_roles("QuoteAgent", "PlatformAdmin")
    c = db.customers.get(cid)
    if c is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "customer not found")
    payload = request.get_json(silent=True) or {}
    if "company_name" in payload:
        c["company_name"] = get_str(payload, "company_name", required=True)
    if "contact_email" in payload:
        c["contact_email"] = get_str(payload, "contact_email", required=True)
    if "contact_phone" in payload:
        c["contact_phone"] = get_str(payload, "contact_phone", required=True)
    if "billing_address" in payload:
        c["billing_address"] = get_str(payload, "billing_address", required=True)
    if "tax_exempt" in payload:
        c["tax_exempt"] = get_bool(payload, "tax_exempt")
    touch(c)
    return success_object(customer_view(c))


@bp.route("/api/v1/customers/<cid>/quotes", methods=["GET"])
def list_customer_quotes(cid):
    user_id, role = require_roles("QuoteAgent", "DispatchManager", "Customer")
    c = db.customers.get(cid)
    if c is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "customer not found")
    if role == "Customer" and user_id != cid:
        raise errors.make_error(errors.ERR_UNAUTHORIZED, "Customer may only access own resources")
    limit, offset = get_pagination()
    status_filter = request.args.get("status")
    items = sorted([q for q in db.quotes.values() if q.get("customer_id") == cid], key=lambda x: x["created_at"])
    if status_filter:
        items = [q for q in items if q.get("status") == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list([quote_view(q) for q in page], limit, offset, total)


@bp.route("/api/v1/customers/<cid>/orders", methods=["GET"])
def list_customer_orders(cid):
    user_id, role = require_roles("QuoteAgent", "DispatchManager", "Customer")
    c = db.customers.get(cid)
    if c is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "customer not found")
    if role == "Customer" and user_id != cid:
        raise errors.make_error(errors.ERR_UNAUTHORIZED, "Customer may only access own resources")
    limit, offset = get_pagination()
    status_filter = request.args.get("status")
    items = sorted([o for o in db.orders.values() if o.get("customer_id") == cid], key=lambda x: x["created_at"])
    if status_filter:
        items = [o for o in items if o.get("status") == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list([order_view(o) for o in page], limit, offset, total)


@bp.route("/api/v1/customers/<cid>/safety-audits", methods=["GET"])
def list_customer_safety_audits(cid):
    user_id, role = require_roles("SafetyOfficer", "Customer")
    c = db.customers.get(cid)
    if c is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "customer not found")
    if role == "Customer" and user_id != cid:
        raise errors.make_error(errors.ERR_UNAUTHORIZED, "Customer may only access own resources")
    limit, offset = get_pagination()
    status_filter = request.args.get("status")
    items = sorted([a for a in db.safety_audits.values() if a.get("customer_id") == cid], key=lambda x: x["created_at"])
    if status_filter:
        items = [a for a in items if a.get("status") == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list([safety_audit_view(a) for a in page], limit, offset, total)
