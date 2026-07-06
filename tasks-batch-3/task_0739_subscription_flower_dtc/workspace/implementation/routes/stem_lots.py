"""Stem lot routes: POST /stem-lots, GET /stem-lots/{id}, GET /stem-lots/{id}/allocations."""
from flask import Blueprint, request

from common import new_common
from errors import ApiError, ERR_STEM_LOT_NOT_FOUND
from middleware import auth_required
import db
from response import created, ok, list_ok
from pagination import parse_pagination, apply_page
from services import validators as v
from services.views import stem_lot_view, allocation_view

bp = Blueprint("stem_lots", __name__)


@bp.route("/stem-lots", methods=["POST"])
@auth_required("FulfillmentOps")
def create_stem_lot():
    body = request.get_json(silent=True) or {}
    v.require_dict(body)
    variety = v.require_str(body, "variety")
    grade = v.require_enum(body, "grade", v.GRADE_ENUM)
    quantity_total = v.require_int(body, "quantity_total", min_value=1)
    unit_cost_cents = v.require_int(body, "unit_cost_cents", min_value=0)
    _sa_dt, sourced_at_str = v.require_datetime(body, "sourced_at")
    shelf_life_hours = v.require_int(body, "shelf_life_hours", min_value=1)

    lot = {
        **new_common(),
        "variety": variety,
        "grade": grade,
        "quantity_total": quantity_total,
        "unit_cost_cents": unit_cost_cents,
        "sourced_at": sourced_at_str,
        "shelf_life_hours": shelf_life_hours,
    }
    db.stem_lots[lot["id"]] = lot
    return created(stem_lot_view(lot))


@bp.route("/stem-lots/<lid>", methods=["GET"])
@auth_required("FulfillmentOps")
def get_stem_lot(lid):
    lot = db.stem_lots.get(lid)
    if lot is None:
        raise ApiError(ERR_STEM_LOT_NOT_FOUND, "stem lot not found", 404)
    return ok(stem_lot_view(lot))


@bp.route("/stem-lots/<lid>/allocations", methods=["GET"])
@auth_required("FulfillmentOps")
def list_lot_allocations(lid):
    limit, offset = parse_pagination()
    lot = db.stem_lots.get(lid)
    if lot is None:
        raise ApiError(ERR_STEM_LOT_NOT_FOUND, "stem lot not found", 404)
    status_filter = request.args.get("status")

    items = [a for a in db.allocations.values() if a["lot_id"] == lid]
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    items.sort(key=lambda a: a["created_at"])
    page, total = apply_page(items, limit, offset)
    return list_ok([allocation_view(a) for a in page], limit, offset, total)
