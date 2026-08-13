"""Restock-notification endpoints (PRD §3.9)."""
from flask import Blueprint, request

import db
from errors import (err_invalid_request, err_not_found, err_invalid_state,
                    err_duplicate_subscription)
from middleware import require_roles, get_json_body, check_account_ownership, scoped_account_id
from response import success_object, success_list, parse_pagination, paginate
from serializers import ser_notification

bp = Blueprint("notifications", __name__)
PREFIX = "/packaging-distribution"

READ_ROLES = ("PlatformAdmin", "CustomerService", "Buyer")
NOTIF_STATUSES = {"ACTIVE", "NOTIFIED", "CANCELLED"}


def _get_notification(notif_id):
    n = db.restock_notifications.get(notif_id)
    if n is None:
        raise err_not_found("Restock notification not found.")
    return n


@bp.route(f"{PREFIX}/restock-notifications", methods=["POST"])
@require_roles("Buyer")
def create_notification():
    body = get_json_body(required=True)
    account_id = body.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        raise err_invalid_request("Missing required field: account_id.")
    product_id = body.get("product_id")
    if not isinstance(product_id, str) or not product_id:
        raise err_invalid_request("Missing required field: product_id.")
    check_account_ownership(account_id)
    if account_id not in db.accounts:
        raise err_not_found("Account not found.")
    if product_id not in db.products:
        raise err_not_found("Product not found.")
    for n in db.restock_notifications.values():
        if (n["account_id"] == account_id and n["product_id"] == product_id
                and n["status"] == "ACTIVE"):
            raise err_duplicate_subscription()
    now = db.now()
    n = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "account_id": account_id,
        "product_id": product_id,
        "status": "ACTIVE",
        "notified_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.restock_notifications[n["id"]] = n
    return success_object(ser_notification(n), status=201)


@bp.route(f"{PREFIX}/restock-notifications", methods=["GET"])
@require_roles(*READ_ROLES)
def list_notifications():
    limit, offset = parse_pagination(request.args)
    account_f = request.args.get("account_id")
    product_f = request.args.get("product_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in NOTIF_STATUSES:
        raise err_invalid_request("Invalid 'status' filter.")
    scoped = scoped_account_id()
    items = sorted(db.restock_notifications.values(), key=lambda n: (n["created_at"], n["_seq"]))
    if scoped is not None:
        items = [n for n in items if n["account_id"] == scoped]
    if account_f is not None:
        items = [n for n in items if n["account_id"] == account_f]
    if product_f is not None:
        items = [n for n in items if n["product_id"] == product_f]
    if status_f is not None:
        items = [n for n in items if n["status"] == status_f]
    page, pagination = paginate(items, limit, offset)
    return success_list([ser_notification(n) for n in page], pagination)


@bp.route(f"{PREFIX}/restock-notifications/<notif_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_notification(notif_id):
    n = _get_notification(notif_id)
    check_account_ownership(n["account_id"])
    return success_object(ser_notification(n))


@bp.route(f"{PREFIX}/restock-notifications/<notif_id>/cancel", methods=["POST"])
@require_roles("Buyer")
def cancel_notification(notif_id):
    n = _get_notification(notif_id)
    check_account_ownership(n["account_id"])
    if n["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE subscription can be cancelled.")
    n["status"] = "CANCELLED"
    db.touch(n)
    return success_object(ser_notification(n))
