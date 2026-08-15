"""Nest sheet read endpoints (cross-order list and detail)."""
from flask import Blueprint

from db import store
from response import ok, paginate
from middleware import get_context, require_roles
from validation import require_path_entity

bp = Blueprint("nest_sheets", __name__)

READ_ROLES = ["ShopManager", "Estimator", "ProductionPlanner"]


@bp.get("/fab/nest-sheets")
def list_nest_sheets():
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    rows = list(store.nest_sheets.values())
    for f in ("order_id", "sheet_stock_id", "remnant_stock_id"):
        rows = paginate.filter(rows, f)
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/fab/nest-sheets/<nest_id>")
def get_nest_sheet(nest_id):
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    return ok(require_path_entity(store.nest_sheets, nest_id))
