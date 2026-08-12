"""ProvisioningOrder and ProvisioningItem endpoints (PRD §3.5)."""

from flask import Blueprint

from auth import require_roles, ALL_ROLES
from db import store, clock
from errors import (ApiError, ERR_ORDER_NOT_FOUND, ERR_ITEM_NOT_FOUND,
                    ERR_ORDER_NOT_DRAFT, ERR_ORDER_NOT_ACTIVE,
                    ERR_INVALID_ITEM_TRANSITION)
from helpers import (touch, get_or_404, children, ser_order, ser_item,
                     sort_indexed)
from sweep import rederive_order_status, refresh_health
from util import (success, get_body, page_params, paged, req_present,
                  as_enum, as_opt_str, bad, fmt_dt)

bp = Blueprint("provisioning", __name__)

ITEM_STATUSES = ("PENDING", "IN_FULFILLMENT", "DONE", "BLOCKED", "CANCELLED")
ALLOWED_TRANSITIONS = {
    ("PENDING", "IN_FULFILLMENT"),
    ("IN_FULFILLMENT", "DONE"),
    ("IN_FULFILLMENT", "BLOCKED"),
    ("BLOCKED", "IN_FULFILLMENT"),
}
ORDER_ACTIVE = ("SUBMITTED", "IN_PROGRESS", "ATTENTION_REQUIRED")


@bp.get("/api/provisioning-orders/<oid>")
def get_order(oid):
    require_roles(*ALL_ROLES)
    order = get_or_404("orders", oid, ERR_ORDER_NOT_FOUND,
                       "ProvisioningOrder")
    return success(ser_order(order))


@bp.post("/api/provisioning-orders/<oid>/submit")
def submit_order(oid):
    require_roles("HRAdmin")
    get_body()
    order = get_or_404("orders", oid, ERR_ORDER_NOT_FOUND,
                       "ProvisioningOrder")
    if order["status"] != "DRAFT":
        raise ApiError(ERR_ORDER_NOT_DRAFT, 409,
                       "Only a DRAFT order can be submitted")
    now = clock.current
    order["status"] = "SUBMITTED"
    order["_submitted_dt"] = now
    order["submitted_at"] = fmt_dt(now)
    touch(order)
    case = store["cases"].get(order["case_id"])
    if case is not None:
        touch(case)
    return success(ser_order(order))


@bp.get("/api/provisioning-orders/<oid>/items")
def order_items(oid):
    require_roles(*ALL_ROLES)
    get_or_404("orders", oid, ERR_ORDER_NOT_FOUND, "ProvisioningOrder")
    limit, offset = page_params()
    records = sort_indexed(children("items", oid, key="order_id"))
    return paged([ser_item(i) for i in records], limit, offset)


@bp.post("/api/provisioning-items/<iid>/transition")
def transition_item(iid):
    require_roles("ITProvisioner")
    body = get_body()
    to = as_enum(req_present(body, "to"), "to", ITEM_STATUSES)
    blocked_reason = as_opt_str(body.get("blocked_reason"), "blocked_reason")
    if to == "BLOCKED" and not blocked_reason:
        bad("blocked_reason is required when transitioning to BLOCKED")
    item = get_or_404("items", iid, ERR_ITEM_NOT_FOUND, "ProvisioningItem")
    order = store["orders"].get(item["order_id"])
    # Stage 6a: the owning order must be active
    if order is None or order["status"] not in ORDER_ACTIVE:
        raise ApiError(ERR_ORDER_NOT_ACTIVE, 409,
                       "Item transitions require an active order")
    # Stage 6b: the (from, to) pair must be one of the four allowed
    if (item["status"], to) not in ALLOWED_TRANSITIONS:
        raise ApiError(ERR_INVALID_ITEM_TRANSITION, 409,
                       f"Transition {item['status']} -> {to} is not allowed")
    item["status"] = to
    if to == "BLOCKED":
        item["blocked_reason"] = blocked_reason
    elif to == "IN_FULFILLMENT":
        item["blocked_reason"] = None  # retry cycle clears the reason
    touch(item)
    rederive_order_status(order)
    return success(ser_item(item))
