"""Scrap credit ledger endpoints."""
from flask import Blueprint

from db import store, new_id, wall_now, touch
from errors import ApiError
from response import ok, created, paginate
from middleware import get_context, require_roles
from validation import parse_body, require_path_entity, resolve_fk
from services.audit import audit
from services.credits import post_scrap_credit

bp = Blueprint("credits", __name__)

READ_ROLES = ["ShopManager", "InventoryClerk", "CustomerRep"]


@bp.post("/fab/scrap-credits")
def create_credit():
    uid, role, _ = get_context()
    require_roles(["InventoryClerk"])
    body = parse_body({
        "customer_id": ("string", True, None),
        "sheet_stock_id": ("string", True, None),
    }, allow_empty=False)
    customer = resolve_fk(store.customers, body["customer_id"], "customer_id")
    sheet = resolve_fk(store.sheet_stock, body["sheet_stock_id"], "sheet_stock_id")
    credit = post_scrap_credit(customer, sheet)
    audit("ScrapCredit", credit["id"], "CREDIT_POSTED", role, uid,
          {"after": {"status": "POSTED", "credit_cents": credit["credit_cents"]}})
    return created(credit)


@bp.get("/fab/scrap-credits")
def list_credits():
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    rows = list(store.scrap_credits.values())
    if role == "CustomerRep":
        rows = [c for c in rows if c["customer_id"] == uid]
    for f in ("customer_id", "status", "sheet_stock_id"):
        rows = paginate.filter(rows, f)
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/fab/scrap-credits/<credit_id>")
def get_credit(credit_id):
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    c = require_path_entity(store.scrap_credits, credit_id)
    if role == "CustomerRep" and c["customer_id"] != uid:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return ok(c)


@bp.post("/fab/scrap-credits/<credit_id>/void")
def void_credit(credit_id):
    uid, role, _ = get_context()
    require_roles(["ShopManager"])
    body = parse_body({"expected_customer_version": ("integer", True, None)}, allow_empty=False)
    c = require_path_entity(store.scrap_credits, credit_id)
    if c["status"] != "POSTED":
        raise ApiError("ERR_CREDIT_NOT_VOIDABLE", 409, "Void requires the credit to be POSTED")
    customer = store.customers[c["customer_id"]]
    if body["expected_customer_version"] != customer["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Customer version has advanced since last read")
    customer["scrap_credit_balance_cents"] -= c["credit_cents"]
    touch(customer)
    c["status"] = "VOID"
    touch(c)
    audit("ScrapCredit", c["id"], "CREDIT_VOIDED", role, uid,
          {"before": {"status": "POSTED"}, "after": {"status": "VOID"}})
    return ok(c)
