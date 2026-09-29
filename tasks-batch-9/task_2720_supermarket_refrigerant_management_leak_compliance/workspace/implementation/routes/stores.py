"""Stores and refrigerant types (PRD 3.1)."""
from decimal import Decimal

from flask import Blueprint, request

import constants
import db
import response
import validate
from middleware import (COMPLIANCE_MANAGER, PLATFORM_ADMIN, endpoint,
                        read_endpoint, require_store_scope)
from services import guards

bp = Blueprint("stores", __name__)

ZERO_1 = Decimal("0.0")
ZERO_2 = Decimal("0.00")


def new_store(name, store_code, state_code, region):
    store = db.new_entity()
    store.update({
        "name": name,
        "store_code": store_code,
        "state_code": state_code,
        "region": region,
        "compliance_status": "COMPLIANT",
        "chronic_leaker_flag": False,
        "regulated_system_count": 0,
        "total_regulated_charge_lbs": ZERO_1,
        "open_leak_event_count": 0,
        "overdue_leak_event_count": 0,
        "mandated_retrofit_count": 0,
        "vented_loss_lbs": ZERO_1,
        "penalty_exposure_total_usd": ZERO_2,
    })
    return store


@bp.post("/stores")
@endpoint([PLATFORM_ADMIN, COMPLIANCE_MANAGER])
def create_store():
    payload = validate.body()
    name = validate.req_str(payload, "name")
    store_code = validate.req_str(payload, "store_code")
    state_code = validate.req_str(payload, "state_code")
    region = validate.req_enum(payload, "region", constants.REGIONS)
    guards.require_unique("stores", "store_code", store_code)
    store = new_store(name, store_code, state_code, region)
    db.insert("stores", store)
    return response.created(store)


@bp.get("/stores")
@read_endpoint
def list_stores():
    filters = {
        "region": request.args.get("region"),
        "compliance_status": request.args.get("compliance_status"),
        "chronic_leaker_flag": response.bool_filter("chronic_leaker_flag"),
    }
    return response.listing(db.values("stores"), filters)


@bp.get("/stores/<store_id>")
@read_endpoint
def get_store(store_id):
    store = db.require("stores", store_id)
    require_store_scope(store["id"])
    return response.ok(store)


@bp.post("/refrigerant-types")
@endpoint([PLATFORM_ADMIN, COMPLIANCE_MANAGER])
def create_refrigerant_type():
    payload = validate.body()
    name = validate.req_str(payload, "name")
    gwp = validate.req_int(payload, "gwp", minimum=0)
    pressure_class = validate.req_enum(payload, "pressure_class",
                                       constants.PRESSURE_CLASSES)
    ods_class = validate.req_enum(payload, "ods_class", constants.ODS_CLASSES)
    phasedown_status = validate.req_enum(payload, "phasedown_status",
                                         constants.PHASEDOWN_STATUSES)
    guards.require_unique("refrigerant_types", "name", name)
    refrigerant_type = db.new_entity()
    refrigerant_type.update({
        "name": name,
        "gwp": gwp,
        "pressure_class": pressure_class,
        "ods_class": ods_class,
        "phasedown_status": phasedown_status,
    })
    db.insert("refrigerant_types", refrigerant_type)
    return response.created(refrigerant_type)


@bp.get("/refrigerant-types")
@read_endpoint
def list_refrigerant_types():
    filters = {
        "phasedown_status": request.args.get("phasedown_status"),
        "ods_class": request.args.get("ods_class"),
    }
    return response.listing(db.values("refrigerant_types"), filters)


@bp.get("/refrigerant-types/<type_id>")
@read_endpoint
def get_refrigerant_type(type_id):
    return response.ok(db.require("refrigerant_types", type_id))
