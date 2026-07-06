"""Customers + reverse-reachability listings for wallet/win-back."""
from flask import Blueprint, request, g

from common import new_common
from errors import (
    ApiError, ERR_CUSTOMER_NOT_FOUND, ERR_NOT_OWNER,
    bad_request,
)
from middleware import auth_required
import db
from response import created, ok, list_ok
from pagination import parse_pagination, apply_page
from services import validators as v
from services.views import customer_view, wallet_entry_view, winback_view

bp = Blueprint("customers", __name__)


def _get_customer_or_404(cid):
    c = db.customers.get(cid)
    if c is None:
        raise ApiError(ERR_CUSTOMER_NOT_FOUND, "customer not found", 404)
    return c


@bp.route("/customers", methods=["POST"])
@auth_required("PlatformAdmin")
def create_customer():
    body = request.get_json(silent=True) or {}
    v.require_dict(body)
    email = v.require_str(body, "email")
    full_name = v.require_str(body, "full_name")
    default_zip = v.optional_str(body, "default_zip")

    # Unique email
    for existing in db.customers.values():
        if existing["email"] == email:
            raise bad_request("email already in use")

    c = {
        **new_common(),
        "email": email,
        "full_name": full_name,
        "default_zip": default_zip,
        "status": "ACTIVE",
    }
    db.customers[c["id"]] = c
    return created(customer_view(c))


@bp.route("/customers/<cid>", methods=["GET"])
@auth_required("Customer", "PlatformAdmin", "BillingAdmin")
def get_customer(cid):
    c = _get_customer_or_404(cid)
    # Customer scope: only own record. PRD §2.1 ownership check.
    if g.user_role == "Customer" and cid != g.user_id:
        raise ApiError(ERR_NOT_OWNER, "not owner", 403)
    return ok(customer_view(c))


@bp.route("/customers/<cid>/wallet-entries", methods=["GET"])
@auth_required("Customer", "BillingAdmin")
def list_wallet_entries(cid):
    limit, offset = parse_pagination()
    c = _get_customer_or_404(cid)
    if g.user_role == "Customer" and cid != g.user_id:
        raise ApiError(ERR_NOT_OWNER, "not owner", 403)

    items = [w for w in db.wallet_entries.values() if w["customer_id"] == cid]
    items.sort(key=lambda w: w["created_at"])
    page, total = apply_page(items, limit, offset)
    return list_ok([wallet_entry_view(w) for w in page], limit, offset, total)


@bp.route("/customers/<cid>/win-back-offers", methods=["GET"])
@auth_required("Customer", "BillingAdmin")
def list_win_back_offers(cid):
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    c = _get_customer_or_404(cid)
    if g.user_role == "Customer" and cid != g.user_id:
        raise ApiError(ERR_NOT_OWNER, "not owner", 403)

    items = [o for o in db.win_back_offers.values() if o["customer_id"] == cid]
    items.sort(key=lambda o: o["created_at"])
    # Materialize views first to trigger lazy EXPIRED transition, then filter.
    views = [winback_view(o) for o in items]
    if status_filter is not None:
        views = [ov for ov in views if ov["status"] == status_filter]
    page, total = apply_page(views, limit, offset)
    return list_ok(page, limit, offset, total)
