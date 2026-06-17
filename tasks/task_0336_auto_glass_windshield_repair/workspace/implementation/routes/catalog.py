"""Catalog/workforce/shop-floor + test clock (PRD 3.1, 3.8)."""
from flask import Blueprint, g

import db
import errors
import response
import validation as V
from errors import ApiError
from middleware import require_roles
from services import helpers as H

bp = Blueprint("catalog", __name__)


def _validate_state(code, field):
    if not isinstance(code, str) or len(code) != 2 or not code.isalpha() or code != code.upper():
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       field + " must be a 2-letter uppercase US state code.")
    return code


# ---------------------------------------------------------------------------
# Glass parts
# ---------------------------------------------------------------------------
@bp.route("/glass-parts", methods=["POST"])
@require_roles("ShopManager")
def create_glass_part():
    body = V.get_json()
    oem_part_number = V.require_str(body, "oem_part_number")
    description = V.opt_str(body, "description")
    unit_price_cents = V.require_int(body, "unit_price_cents")
    adas_compatible = V.opt_bool(body, "adas_compatible", False)
    on_hand_qty = V.opt_int(body, "on_hand_qty", 0)

    if unit_price_cents < 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "unit_price_cents must be >= 0.")
    if on_hand_qty < 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "on_hand_qty must be >= 0.")

    part = db.stamp_new({
        "oem_part_number": oem_part_number,
        "description": description,
        "adas_compatible": adas_compatible,
        "unit_price_cents": unit_price_cents,
        "on_hand_qty": on_hand_qty,
        "reserved_qty": 0,
    })
    db.glass_parts[part["id"]] = part
    return response.success(H.view(part), 201)


@bp.route("/glass-parts/<pid>", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager")
def get_glass_part(pid):
    return response.success(H.view(H.get_glass_part(pid)))


@bp.route("/glass-parts", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager")
def list_glass_parts():
    from flask import request
    limit, offset = V.parse_pagination()
    oem = request.args.get("oem_part_number")
    adas_raw = request.args.get("adas_compatible")
    items = list(db.glass_parts.values())
    if oem is not None:
        items = [p for p in items if p["oem_part_number"] == oem]
    if adas_raw is not None:
        want = adas_raw.lower() == "true"
        items = [p for p in items if p["adas_compatible"] == want]
    items = db.sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return response.paginated(H.view_list(page), limit, offset, total)


@bp.route("/glass-parts/<pid>/restock", methods=["PATCH"])
@require_roles("ShopManager")
def restock_glass_part(pid):
    part = H.get_glass_part(pid)
    body = V.get_json()
    add_qty = V.require_int(body, "add_qty")
    if add_qty < 1:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "add_qty must be >= 1.")
    part["on_hand_qty"] += add_qty
    db.touch(part)
    return response.success(H.view(part))


# ---------------------------------------------------------------------------
# Technicians
# ---------------------------------------------------------------------------
@bp.route("/technicians", methods=["POST"])
@require_roles("ShopManager")
def create_technician():
    body = V.get_json()
    full_name = V.require_str(body, "full_name")
    home_state = V.require_str(body, "home_state")
    _validate_state(home_state, "home_state")
    can_mobile = V.opt_bool(body, "can_mobile", True)
    adas_certified = V.opt_bool(body, "adas_certified", False)

    tech = db.stamp_new({
        "full_name": full_name,
        "can_mobile": can_mobile,
        "adas_certified": adas_certified,
        "home_state": home_state,
    })
    db.technicians[tech["id"]] = tech
    return response.success(H.view(tech), 201)


@bp.route("/technicians/<tid>", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager")
def get_technician(tid):
    return response.success(H.view(H.get_technician(tid)))


# ---------------------------------------------------------------------------
# Service bays
# ---------------------------------------------------------------------------
@bp.route("/service-bays", methods=["POST"])
@require_roles("ShopManager")
def create_service_bay():
    body = V.get_json()
    name = V.require_str(body, "name")
    bay_type = V.require_enum(body, "bay_type", {"INSTALL", "CALIBRATION"})
    cleanroom = V.opt_bool(body, "cleanroom", False)

    bay = db.stamp_new({
        "name": name,
        "bay_type": bay_type,
        "cleanroom": cleanroom,
    })
    db.service_bays[bay["id"]] = bay
    return response.success(H.view(bay), 201)


@bp.route("/service-bays/<bid>", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager")
def get_service_bay(bid):
    return response.success(H.view(H.get_service_bay(bid)))


# ---------------------------------------------------------------------------
# Test-driving clock (PRD 3.8)
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("ShopManager")
def set_clock():
    body = V.get_json()
    dt = V.require_datetime(body, "to_iso8601")
    db.set_clock(dt)
    return response.success({"current_utc": V.to_iso(dt)})
