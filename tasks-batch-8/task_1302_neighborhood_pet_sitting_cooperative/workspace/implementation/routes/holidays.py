"""HolidayWindow endpoints: create/list/get/disable."""

from decimal import Decimal

from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import body, bool_filter, paginate, require_roles
from response import created, ok
from serializers import window_view
from util import base_entity, parse_dt, to_dec, touch

bp = Blueprint("holidays", __name__)


def get_window_or_404(window_id):
    window = db.store["windows"].get(window_id)
    if window is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"HolidayWindow {window_id} does not exist")
    return window


@bp.post("/coop/holiday-windows")
def create_window():
    require_roles("CoopAdmin")
    data = body()
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "name is required")
    try:
        window_start = parse_dt(data.get("window_start"))
        window_end = parse_dt(data.get("window_end"))
    except (TypeError, ValueError):
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "window_start and window_end must be valid ISO 8601 datetimes",
        )
    if window_end <= window_start:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "window_end must be after window_start"
        )
    try:
        demand_multiplier = to_dec(data.get("demand_multiplier"))
    except (TypeError, ValueError, ArithmeticError):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "demand_multiplier must be a number"
        )
    if demand_multiplier < Decimal("1.0") or demand_multiplier > Decimal("3.0"):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "demand_multiplier must be in [1.0, 3.0]"
        )
    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "enabled must be a boolean")
    window = base_entity()
    window.update(
        {
            "name": name,
            "window_start": window_start,
            "window_end": window_end,
            "demand_multiplier": demand_multiplier,
            "enabled": enabled,
        }
    )
    db.store["windows"][window["id"]] = window
    return created(window_view(window))


@bp.get("/coop/holiday-windows")
def list_windows():
    require_roles("CoopAdmin", "Member")
    items = list(db.store["windows"].values())
    enabled = bool_filter(request.args.get("enabled"))
    if enabled is not None:
        items = [w for w in items if w["enabled"] == enabled]
    return paginate(items, window_view)


@bp.get("/coop/holiday-windows/<window_id>")
def get_window(window_id):
    require_roles("CoopAdmin", "Member")
    return ok(window_view(get_window_or_404(window_id)))


@bp.post("/coop/holiday-windows/<window_id>/disable")
def disable_window(window_id):
    require_roles("CoopAdmin")
    window = get_window_or_404(window_id)
    window["enabled"] = False
    touch(window)
    return ok(window_view(window))
