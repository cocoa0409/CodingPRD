"""Sheet stock intake and lifecycle endpoints."""
from flask import Blueprint

from db import store, new_id, touch, new_common
from errors import ApiError
from response import ok, created, paginate
from middleware import get_context, require_roles
from validation import parse_body, require_path_entity, resolve_fk
from services.audit import audit

bp = Blueprint("stock", __name__)

READ_ROLES = ["ShopManager", "Estimator", "ProductionPlanner", "InventoryClerk"]


@bp.post("/fab/sheet-stock")
def create_stock():
    uid, role, _ = get_context()
    require_roles(["InventoryClerk"])
    body = parse_body({
        "grade_id": ("string", True, None),
        "thickness_mm": ("number", True, None),
        "width_mm": ("integer", True, None),
        "height_mm": ("integer", True, None),
    }, allow_empty=False)
    resolve_fk(store.material_grades, body["grade_id"], "grade_id")
    if body["width_mm"] <= 0 or body["height_mm"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "width_mm and height_mm must be positive")
    sheet = {
        "id": new_id(),
        "grade_id": body["grade_id"],
        "thickness_mm": body["thickness_mm"],
        "width_mm": body["width_mm"],
        "height_mm": body["height_mm"],
        "kind": "FULL_SHEET" if (body["width_mm"] == 1200 and body["height_mm"] == 2400) else "REMNANT",
        "status": "AVAILABLE",
        "source_order_id": None,
    }
    new_common(sheet)
    store.sheet_stock[sheet["id"]] = sheet
    audit("SheetStock", sheet["id"], "STOCK_RECEIVED", role, uid,
          {"after": {"kind": sheet["kind"], "status": "AVAILABLE"}})
    return created(sheet)


@bp.get("/fab/sheet-stock")
def list_stock():
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    rows = list(store.sheet_stock.values())
    for f in ("grade_id", "status", "kind", "source_order_id"):
        rows = paginate.filter(rows, f)
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/fab/sheet-stock/<sheet_id>")
def get_stock(sheet_id):
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    return ok(require_path_entity(store.sheet_stock, sheet_id))


@bp.post("/fab/sheet-stock/<sheet_id>/scrap")
def scrap_stock(sheet_id):
    uid, role, _ = get_context()
    require_roles(["InventoryClerk"])
    s = require_path_entity(store.sheet_stock, sheet_id)
    if s["status"] != "AVAILABLE":
        raise ApiError("ERR_STOCK_NOT_AVAILABLE", 409, "Scrap requires stock in AVAILABLE status")
    s["status"] = "SCRAPPED"
    touch(s)
    audit("SheetStock", s["id"], "STOCK_SCRAPPED", role, uid,
          {"before": {"status": "AVAILABLE"}, "after": {"status": "SCRAPPED"}})
    return ok(s)
