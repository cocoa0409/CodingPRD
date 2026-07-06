"""SpecialOrder routes."""
from flask import Blueprint, request
from db import DB
from errors import (
    not_found, invalid_request, invalid_state, unauthorized, stale_version,
    ApiError, ERR_SPECIAL_ORDER_INVALID_STATE,
)
from middleware import (
    auth_context, require_role, require_json,
    parse_pagination, sort_by_created, paginate,
)
from response import ok, created, ok_list
from services.common import stamp_common, bump
from services.validation import require_fields, require_enum, require_int, require_string

bp = Blueprint("special_orders", __name__)

SERVICE_TYPES = {"PROCUREMENT", "REPOTTING"}
STATUSES = {"REQUESTED", "QUOTED", "RE_QUOTED", "CUSTOMER_APPROVED", "FULFILLED", "CANCELLED"}


@bp.post("/special-orders")
def create_special_order():
    role, user_id = auth_context()
    require_role(role, {"Customer", "ShopStaff"})
    payload = require_json()
    require_fields(payload, ["customer_id", "service_type", "sku_description"])
    cid = payload["customer_id"]
    if cid not in DB.customers:
        raise not_found("Customer")
    if role == "Customer" and user_id != cid:
        raise unauthorized("Customer must act for self")
    require_enum(payload["service_type"], SERVICE_TYPES, "service_type")
    desc = require_string(payload, "sku_description", allow_empty=False)
    entity = {
        **stamp_common(full=True),
        "customer_id": cid,
        "service_type": payload["service_type"],
        "sku_description": desc,
        "status": "REQUESTED",
        "quoted_price_cents": 0,
        "revision_count": 0,
    }
    DB.special_orders[entity["id"]] = entity
    return created(entity)


@bp.post("/special-orders/<sid>/quote")
def quote(sid):
    role, _ = auth_context()
    require_role(role, {"Manager"})
    so = DB.special_orders.get(sid)
    if not so:
        raise not_found("SpecialOrder")
    payload = require_json()
    require_fields(payload, ["quoted_price_cents"])
    qp = require_int(payload, "quoted_price_cents", minimum=0)
    if so["status"] not in ("REQUESTED", "RE_QUOTED"):
        raise ApiError(ERR_SPECIAL_ORDER_INVALID_STATE, 409, "invalid state for quote")
    so["status"] = "QUOTED"
    so["quoted_price_cents"] = qp
    bump(so)
    return ok(so)


@bp.post("/special-orders/<sid>/re-quote")
def re_quote(sid):
    role, _ = auth_context()
    require_role(role, {"Manager"})
    so = DB.special_orders.get(sid)
    if not so:
        raise not_found("SpecialOrder")
    payload = require_json()
    require_fields(payload, ["quoted_price_cents"])
    qp = require_int(payload, "quoted_price_cents", minimum=0)
    if so["status"] != "QUOTED":
        raise ApiError(ERR_SPECIAL_ORDER_INVALID_STATE, 409, "invalid state for re-quote")
    if so["revision_count"] + 1 > 3:
        raise ApiError(ERR_SPECIAL_ORDER_INVALID_STATE, 409, "revision cap exceeded")
    so["status"] = "RE_QUOTED"
    so["quoted_price_cents"] = qp
    so["revision_count"] = so["revision_count"] + 1
    bump(so)
    return ok(so)


@bp.post("/special-orders/<sid>/customer-approve")
def customer_approve(sid):
    role, user_id = auth_context()
    require_role(role, {"Customer"})
    so = DB.special_orders.get(sid)
    if not so:
        raise not_found("SpecialOrder")
    if user_id != so["customer_id"]:
        raise unauthorized("not owner")
    payload = require_json()
    require_fields(payload, ["expected_special_order_version"])
    exp = payload["expected_special_order_version"]
    if not isinstance(exp, int) or isinstance(exp, bool):
        raise invalid_request("expected_special_order_version must be integer")
    if so["status"] not in ("QUOTED", "RE_QUOTED"):
        raise ApiError(ERR_SPECIAL_ORDER_INVALID_STATE, 409, "not approvable state")
    if exp != so["version"]:
        raise stale_version("special order version mismatch")
    so["status"] = "CUSTOMER_APPROVED"
    bump(so)
    return ok(so)


@bp.get("/special-orders")
def list_special_orders():
    role, user_id = auth_context()
    require_role(role, {"Customer", "Manager"})
    limit, offset = parse_pagination(request.args)
    customer_id = request.args.get("customer_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in STATUSES:
        raise invalid_request("invalid status filter")
    rows = list(DB.special_orders.values())
    if customer_id:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if status_f:
        rows = [r for r in rows if r["status"] == status_f]
    if role == "Customer":
        rows = [r for r in rows if r["customer_id"] == user_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit=limit, offset=offset, total_count=total)


@bp.get("/special-orders/<sid>")
def get_special_order(sid):
    role, user_id = auth_context()
    require_role(role, {"Customer", "Manager"})
    so = DB.special_orders.get(sid)
    if not so:
        raise not_found("SpecialOrder")
    if role == "Customer" and user_id != so["customer_id"]:
        raise unauthorized("not owner")
    return ok(so)
