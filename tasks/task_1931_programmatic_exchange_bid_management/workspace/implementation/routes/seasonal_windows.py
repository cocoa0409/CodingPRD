"""Seasonal pricing window endpoints (PRD §3.2)."""

from flask import Blueprint, request

from db import store
from errors import not_found, unauthorized, ApiError, ERR_INVALID_TIME_RANGE, ERR_SEASONAL_WINDOW_OVERLAP
from middleware import require_roles, ALL_ROLES, ROLE_PUBLISHER_MANAGER
from response import success_object, success_list, paginate
from util import get_body, req_str, req_int, req_date
from services.core import (
    base_record, touch, serialize_window, recompute_package_floor, _sorted,
)

bp = Blueprint("seasonal_windows", __name__)


@bp.route("/seasonal-windows", methods=["POST"])
def create_window():
    role, user_id = require_roles([ROLE_PUBLISHER_MANAGER])
    body = get_body()
    package_id = req_str(body, "package_id")
    name = req_str(body, "name")
    start_date = req_date(body, "start_date")
    end_date = req_date(body, "end_date")
    multiplier = req_int(body, "multiplier_bps", min_v=1, max_v=100000)
    # existence
    pkg = store.packages.get(package_id)
    if pkg is None:
        raise not_found("InventoryPackage not found")
    # ownership (stage 6)
    if pkg["publisher_id"] != user_id:
        raise unauthorized("Package belongs to a different publisher")
    # interval sanity (stage 9): inclusive bounds, start on or before end
    if start_date > end_date:
        raise ApiError(ERR_INVALID_TIME_RANGE, 422, "start_date must be on or before end_date")
    # closed-interval overlap on the same package (stage 10); strict adjacency
    # (one window begins the day after the other ends) is allowed
    for w in store.windows.values():
        if w["package_id"] != package_id:
            continue
        if start_date <= w["end_date"] and w["start_date"] <= end_date:
            raise ApiError(ERR_SEASONAL_WINDOW_OVERLAP, 409,
                           "Window overlaps an existing window on the same package")
    window = base_record()
    window.update({
        "package_id": package_id,
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "multiplier_bps": multiplier,
    })
    store.windows[window["id"]] = window
    # floor recompute; the package version moves only when the multiplier
    # actually changes (§3.2)
    if recompute_package_floor(pkg):
        touch(pkg)
    return success_object(serialize_window(window), 201)


@bp.route("/seasonal-windows", methods=["GET"])
def list_windows():
    require_roles(ALL_ROLES)
    package_id = request.args.get("package_id")
    items = list(store.windows.values())
    if package_id is not None:
        items = [w for w in items if w["package_id"] == package_id]
    page, limit, offset, total = paginate(_sorted(items), request.args)
    return success_list([serialize_window(w) for w in page], limit, offset, total)


@bp.route("/seasonal-windows/<windowId>", methods=["GET"])
def get_window(windowId):
    require_roles(ALL_ROLES)
    w = store.windows.get(windowId)
    if w is None:
        raise not_found("SeasonalPricingWindow not found")
    return success_object(serialize_window(w))


@bp.route("/seasonal-windows/<windowId>", methods=["DELETE"])
def delete_window(windowId):
    role, user_id = require_roles([ROLE_PUBLISHER_MANAGER])
    w = store.windows.get(windowId)
    if w is None:
        raise not_found("SeasonalPricingWindow not found")
    pkg = store.packages.get(w["package_id"])
    if pkg is None or pkg["publisher_id"] != user_id:
        raise unauthorized("Window belongs to a different publisher")
    del store.windows[windowId]
    if pkg is not None and recompute_package_floor(pkg):
        touch(pkg)
    # 204 No Content with an empty body (PRD §4)
    return "", 204
