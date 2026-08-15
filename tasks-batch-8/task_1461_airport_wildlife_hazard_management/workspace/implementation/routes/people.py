"""Biologists, ATC controllers, regulator agents."""
from flask import Blueprint, request

import errors as E
from auth import authenticate, require_roles
from constants import AGENCIES
from db import store
from util import (body, validate_payload, check_fk, get_or_404, list_response,
                  ok_object, new_entity, serialize, parse_bool_param)

bp = Blueprint("people", __name__, url_prefix="/wildlife")


# ------------------------------------------------------------- biologists
@bp.post("/biologists")
def create_biologist():
    uid, role = authenticate()
    require_roles(role, ("AirportAdmin",))
    data = validate_payload(body(), [
        ("full_name", "str", True),
        ("certification_id", "str", True),
        ("airport_id", "str", True),
        ("is_senior", "bool", False),
        ("active", "bool", False),
    ])
    check_fk("airport_id", data["airport_id"], store.airports, "airport")
    for b in store.biologists.values():
        if b["certification_id"] == data["certification_id"]:
            raise E.invalid_request("certification_id must be unique")
    rec = new_entity(store.biologists, {
        "full_name": data["full_name"],
        "certification_id": data["certification_id"],
        "airport_id": data["airport_id"],
        "is_senior": data.get("is_senior", False),
        "active": data.get("active", True),
    })
    return ok_object(serialize(rec), 201)


@bp.get("/biologists")
def list_biologists():
    uid, role = authenticate()
    require_roles(role, ("AirportAdmin", "WildlifeBiologist", "RegulatorAgent"))
    airport_id = request.args.get("airport_id")
    is_senior = parse_bool_param(request.args.get("is_senior"), "is_senior")
    active = parse_bool_param(request.args.get("active"), "active")
    rows = [b for b in store.biologists.values()
            if (airport_id is None or b["airport_id"] == airport_id)
            and (is_senior is None or b["is_senior"] == is_senior)
            and (active is None or b["active"] == active)]
    return list_response(rows)


@bp.get("/biologists/<rid>")
def get_biologist(rid):
    uid, role = authenticate()
    require_roles(role, ("AirportAdmin", "WildlifeBiologist", "RegulatorAgent"))
    return ok_object(serialize(get_or_404(store.biologists, rid, "biologist")))


# ------------------------------------------------------------- atc controllers
@bp.post("/atc-controllers")
def create_controller():
    uid, role = authenticate()
    require_roles(role, ("AirportAdmin",))
    data = validate_payload(body(), [
        ("full_name", "str", True),
        ("facility_id", "str", True),
        ("airport_id", "str", True),
        ("active", "bool", False),
    ])
    check_fk("airport_id", data["airport_id"], store.airports, "airport")
    rec = new_entity(store.atc_controllers, {
        "full_name": data["full_name"],
        "facility_id": data["facility_id"],
        "airport_id": data["airport_id"],
        "active": data.get("active", True),
    })
    return ok_object(serialize(rec), 201)


@bp.get("/atc-controllers")
def list_controllers():
    uid, role = authenticate()
    require_roles(role, ("AirportAdmin", "ATCController"))
    airport_id = request.args.get("airport_id")
    rows = [c for c in store.atc_controllers.values()
            if airport_id is None or c["airport_id"] == airport_id]
    return list_response(rows)


@bp.get("/atc-controllers/<rid>")
def get_controller(rid):
    uid, role = authenticate()
    require_roles(role, ("AirportAdmin", "ATCController"))
    return ok_object(serialize(get_or_404(store.atc_controllers, rid, "atc controller")))


# ------------------------------------------------------------- regulators
@bp.post("/regulators")
def create_regulator():
    uid, role = authenticate()
    require_roles(role, ("AirportAdmin",))
    data = validate_payload(body(), [
        ("full_name", "str", True),
        ("agency", "enum", True, {"values": AGENCIES}),
        ("badge_number", "str", True),
    ])
    for r in store.regulators.values():
        if r["badge_number"] == data["badge_number"]:
            raise E.invalid_request("badge_number must be unique")
    rec = new_entity(store.regulators, {
        "full_name": data["full_name"],
        "agency": data["agency"],
        "badge_number": data["badge_number"],
    })
    return ok_object(serialize(rec), 201)


@bp.get("/regulators/<rid>")
def get_regulator(rid):
    uid, role = authenticate()
    require_roles(role, ("AirportAdmin", "RegulatorAgent"))
    return ok_object(serialize(get_or_404(store.regulators, rid, "regulator agent")))
