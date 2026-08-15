"""Properties, buildings, units (PRD §3.1)."""
from flask import Blueprint

import errors as E
from errors import ApiError
from db import store, new_common_fields, touch
from middleware import (auth, require_role, body, v_str, v_int, v_enum,
                        paginate)
from response import ok_object, ok_list
from services.core import (get_property, get_building, property_of_building,
                           require_active_property)
from services.serializers import property_view, building_view, unit_view

bp = Blueprint("portfolio", __name__)

PM = ("PropertyManager",)
ALL = ("PropertyManager", "Technician", "ComplianceAuditor")


# ------------------------------ Properties ---------------------------------

@bp.route("/pm/properties", methods=["POST"])
def create_property():
    _, role = auth()
    require_role(role, PM)
    data = body()
    # No referenced ids and no property-active gate: field shape only.
    code = v_str(data, "property_code")
    name = v_str(data, "display_name")
    lead = v_int(data, "notice_lead_hours", minv=24)
    rate = v_int(data, "default_labor_rate_cents_per_hour", minv=1)
    for p in store.properties.values():
        if p["property_code"] == code:
            raise ApiError(E.ERR_INVALID_REQUEST, 400,
                           "property_code %r already exists" % code)
    rec = new_common_fields()
    rec.update({
        "property_code": code,
        "display_name": name,
        "notice_lead_hours": lead,
        "default_labor_rate_cents_per_hour": rate,
        "status": "ACTIVE",
    })
    store.properties[rec["id"]] = rec
    return ok_object(property_view(rec), 201)


@bp.route("/pm/properties/<property_id>", methods=["GET"])
def get_property_route(property_id):
    _, role = auth()
    require_role(role, ALL)
    prop = get_property(property_id)
    return ok_object(property_view(prop), 200)


@bp.route("/pm/properties/<property_id>/archive", methods=["POST"])
def archive_property(property_id):
    _, role = auth()
    require_role(role, PM)
    prop = get_property(property_id)
    require_active_property(prop)
    prop["status"] = "ARCHIVED"
    touch(prop)
    return ok_object(property_view(prop), 200)


# ------------------------------ Buildings ----------------------------------

@bp.route("/pm/buildings", methods=["POST"])
def create_building():
    _, role = auth()
    require_role(role, PM)
    data = body()
    # Stage 3/4: referenced property must exist and be ACTIVE.
    prop = None
    if data.get("property_id") is not None:
        prop = get_property(data["property_id"])
        require_active_property(prop)
    # Stage 15: field shape, in declared input order.
    pid = v_str(data, "property_id")
    label = v_str(data, "building_label")
    floors = v_int(data, "floors", minv=1)
    if prop is None:
        prop = get_property(pid)
        require_active_property(prop)
    rec = new_common_fields()
    rec.update({
        "property_id": prop["id"],
        "building_label": label,
        "floors": floors,
    })
    store.buildings[rec["id"]] = rec
    return ok_object(building_view(rec), 201)


@bp.route("/pm/buildings/<building_id>", methods=["GET"])
def get_building_route(building_id):
    _, role = auth()
    require_role(role, ALL)
    b = get_building(building_id)
    return ok_object(building_view(b), 200)


@bp.route("/pm/properties/<property_id>/buildings", methods=["GET"])
def list_buildings(property_id):
    _, role = auth()
    require_role(role, ALL)
    prop = get_property(property_id)
    rows = [b for b in store.buildings.values() if b["property_id"] == prop["id"]]
    page, limit, offset, total = paginate(rows)
    return ok_list([building_view(b) for b in page], limit, offset, total)


# ------------------------------ Units --------------------------------------

@bp.route("/pm/units", methods=["POST"])
def create_unit():
    _, role = auth()
    require_role(role, PM)
    data = body()
    # Stage 3/4: referenced building must exist; its property must be ACTIVE.
    b = None
    if data.get("building_id") is not None:
        b = get_building(data["building_id"])
        require_active_property(property_of_building(b))
    # Stage 15: field shape, declared input order.
    bid = v_str(data, "building_id")
    number = v_str(data, "unit_number")
    occ = v_enum(data, "occupancy_status", ("OCCUPIED", "VACANT"))
    if b is None:
        b = get_building(bid)
        require_active_property(property_of_building(b))
    for u in store.units.values():
        if u["building_id"] == b["id"] and u["unit_number"] == number:
            raise ApiError(E.ERR_INVALID_REQUEST, 400,
                           "unit_number %r already exists in building" % number)
    rec = new_common_fields()
    rec.update({
        "building_id": b["id"],
        "unit_number": number,
        "occupancy_status": occ,
    })
    store.units[rec["id"]] = rec
    return ok_object(unit_view(rec), 201)


@bp.route("/pm/buildings/<building_id>/units", methods=["GET"])
def list_units(building_id):
    _, role = auth()
    require_role(role, ALL)
    b = get_building(building_id)
    rows = [u for u in store.units.values() if u["building_id"] == b["id"]]
    page, limit, offset, total = paginate(rows)
    return ok_list([unit_view(u) for u in page], limit, offset, total)
