"""ExpensePool and ExpenseLineItem endpoints (PRD §3.1, §3.2)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    APIError, ERR_NOT_FOUND, ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
)
from middleware import auth_required, ALL_ROLES, PROPERTY_MANAGER, ACCOUNTANT
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_fields, serialize, serialize_list, is_int, is_number, is_bool,
    parse_pagination, paginate, order_by_created,
)
from services.common import new_common_fields, touch
from services.calculations import compute_total_recoverable_cents

bp = Blueprint("expense_pools", __name__)

DENOMINATORS = {"TOTAL_RENTABLE", "OCCUPIED"}
CATEGORIES = {
    "LANDSCAPING", "SECURITY", "UTILITIES", "INSURANCE",
    "MANAGEMENT", "TAXES", "REPAIRS", "SNOW_REMOVAL",
}
RECOVERABILITIES = {"RECOVERABLE", "NON_RECOVERABLE", "CAPPED_CONTROLLABLE"}


@bp.post("/expense-pools")
def create_pool():
    auth_required({PROPERTY_MANAGER, ACCOUNTANT})()
    body = get_body()
    require_fields(body, ["property_id", "pool_year"])

    property_id = body["property_id"]
    if db.properties.get(property_id) is None:
        raise APIError(ERR_FK_NOT_FOUND, 404, "property_id references a non-existent property")

    pool_year = body["pool_year"]
    if not is_int(pool_year) or pool_year < 2000:
        raise APIError(ERR_INVALID_REQUEST, 400, "pool_year must be an integer >= 2000")

    denom = body.get("pro_rata_denominator", "TOTAL_RENTABLE")
    if denom not in DENOMINATORS:
        raise APIError(ERR_INVALID_REQUEST, 400, "pro_rata_denominator must be TOTAL_RENTABLE or OCCUPIED")

    admin_fee_pct = body.get("admin_fee_pct", 0.0)
    if not is_number(admin_fee_pct) or not (0 <= admin_fee_pct <= 1):
        raise APIError(ERR_INVALID_REQUEST, 400, "admin_fee_pct must be in [0, 1]")

    pool = {
        **new_common_fields(),
        "property_id": property_id,
        "pool_year": pool_year,
        "pro_rata_denominator": denom,
        "admin_fee_pct": admin_fee_pct,
        "status": "OPEN",
        "total_recoverable_cents": 0,
    }
    db.expense_pools[pool["id"]] = pool
    return ok_object(serialize(pool), http_status=201)


@bp.get("/expense-pools/<pid>")
def get_pool(pid):
    auth_required(ALL_ROLES)()
    p = db.expense_pools.get(pid)
    if p is None:
        raise APIError(ERR_NOT_FOUND, 404, "Expense pool not found")
    return ok_object(serialize(p))


@bp.post("/expense-pools/<pid>/line-items")
def add_line_item(pid):
    auth_required({PROPERTY_MANAGER, ACCOUNTANT})()
    pool = db.expense_pools.get(pid)
    if pool is None:
        raise APIError(ERR_NOT_FOUND, 404, "Expense pool not found")
    body = get_body()
    require_fields(body, ["category", "amount_cents"])

    category = body["category"]
    if category not in CATEGORIES:
        raise APIError(ERR_INVALID_REQUEST, 400, "category is not a valid expense category")

    amount_cents = body["amount_cents"]
    if not is_int(amount_cents) or amount_cents < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "amount_cents must be a non-negative integer")

    recoverability = body.get("recoverability", "RECOVERABLE")
    if recoverability not in RECOVERABILITIES:
        raise APIError(ERR_INVALID_REQUEST, 400, "recoverability is out of range")

    is_variable = body.get("is_variable", False)
    if not is_bool(is_variable):
        raise APIError(ERR_INVALID_REQUEST, 400, "is_variable must be a boolean")

    item = {
        **new_common_fields(),
        "pool_id": pid,
        "category": category,
        "amount_cents": amount_cents,
        "recoverability": recoverability,
        "is_variable": is_variable,
    }
    db.expense_line_items[item["id"]] = item

    # Cascade: recompute pool total and bump pool version (PRD §2.6).
    pool["total_recoverable_cents"] = compute_total_recoverable_cents(pool)
    touch(pool)

    return ok_object(serialize(item), http_status=201)


@bp.get("/expense-pools/<pid>/line-items")
def list_line_items(pid):
    auth_required({PROPERTY_MANAGER, ACCOUNTANT})()
    if db.expense_pools.get(pid) is None:
        raise APIError(ERR_NOT_FOUND, 404, "Expense pool not found")
    limit, offset = parse_pagination()
    items = order_by_created([li for li in db.expense_line_items.values() if li["pool_id"] == pid])
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.delete("/expense-pools/<pid>/line-items/<item_id>")
def remove_line_item(pid, item_id):
    auth_required({PROPERTY_MANAGER, ACCOUNTANT})()
    # Path resources validated left-to-right (PRD §2.6).
    pool = db.expense_pools.get(pid)
    if pool is None:
        raise APIError(ERR_NOT_FOUND, 404, "Expense pool not found")
    item = db.expense_line_items.get(item_id)
    if item is None or item["pool_id"] != pid:
        raise APIError(ERR_NOT_FOUND, 404, "Line item not found on this pool")

    # Removal permitted only while the pool is still OPEN (PRD §3.2).
    if pool["status"] != "OPEN":
        raise APIError(ERR_INVALID_STATE, 409, "Line items can only be removed from an OPEN pool")

    del db.expense_line_items[item_id]
    pool["total_recoverable_cents"] = compute_total_recoverable_cents(pool)
    touch(pool)

    return ok_object(serialize(pool))
