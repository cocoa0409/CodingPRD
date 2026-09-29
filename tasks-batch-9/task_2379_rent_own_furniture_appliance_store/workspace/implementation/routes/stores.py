"""Stores, inventory units, delivery crews and the day-close checkpoint."""

from flask import Blueprint

import middleware
import response
import validators
from db import base_row, db, public
from errors import ApiError
from routes import common
from services import day_close, domain

bp = Blueprint("stores", __name__)

CATEGORIES = ("FURNITURE", "APPLIANCE")
CREW_STATUSES = ("ACTIVE", "INACTIVE")


@bp.post("/stores")
def create_store():
    middleware.authenticate((middleware.PLATFORM_ADMIN,))
    body = validators.json_body()
    name = validators.string(body, "name", min_len=1, max_len=120)
    code = validators.state_code(body, "state_code")
    capacity = validators.integer(
        body, "service_bay_capacity", required=False, default=1, minimum=1
    )
    domain.require_rule_for_state(code)

    store = base_row()
    store["name"] = name
    store["state_code"] = code
    store["service_bay_capacity"] = capacity
    store["units_on_rent_count"] = 0
    store["units_in_service_count"] = 0
    store["service_intake_open"] = True
    db.stores[store["id"]] = store
    return response.object_response(public(store), 201)


@bp.get("/stores/<store_id>")
def read_store(store_id):
    middleware.authenticate(middleware.STAFF_ROLES)
    store = domain.require_store(store_id)
    return response.object_response(public(store))


@bp.get("/stores")
def list_stores():
    middleware.authenticate(middleware.STAFF_ROLES)
    return common.paged(list(db.stores.values()), filters=("state_code",))


@bp.post("/stores/<store_id>/day-close")
def run_day_close(store_id):
    user_id, _ = middleware.authenticate(
        (middleware.PLATFORM_ADMIN, middleware.STORE_MANAGER)
    )
    store = domain.require_store(store_id)
    validators.json_body()
    return response.object_response(day_close.run(store))


# ------------------------------------------------------------------ inventory


@bp.post("/stores/<store_id>/inventory-units")
def create_inventory_unit(store_id):
    middleware.authenticate((middleware.PLATFORM_ADMIN, middleware.STORE_MANAGER))
    store = domain.require_store(store_id)
    body = validators.json_body()
    model_code = validators.string(body, "model_code", min_len=1)
    category = validators.enum(body, "category", CATEGORIES)
    serial = validators.string(body, "serial_number", min_len=1)
    cash_price = validators.integer(body, "cash_price_cents", minimum=1000)

    for unit in db.units.values():
        if unit["store_id"] == store["id"] and unit["serial_number"] == serial:
            raise ApiError("ERR_DUPLICATE_SERIAL")

    unit = base_row()
    unit["store_id"] = store["id"]
    unit["model_code"] = model_code
    unit["category"] = category
    unit["serial_number"] = serial
    unit["cash_price_cents"] = cash_price
    unit["condition_grade"] = "NEW"
    unit["rent_cycle_count"] = 0
    unit["status"] = "AVAILABLE"
    unit["accumulated_rent_received_cents"] = 0
    unit["residual_value_cents"] = 0
    unit["residual_valuation_basis"] = "NONE"
    unit["replaced_unit_id"] = None
    unit["retired_reason"] = "NONE"
    db.units[unit["id"]] = unit
    return response.object_response(public(unit), 201)


@bp.get("/stores/<store_id>/inventory-units")
def list_store_inventory(store_id):
    middleware.authenticate(middleware.STAFF_ROLES)
    store = domain.require_store(store_id)
    rows = [u for u in db.units.values() if u["store_id"] == store["id"]]
    return common.paged(rows, filters=("status",))


@bp.get("/inventory-units/<unit_id>")
def read_inventory_unit(unit_id):
    middleware.authenticate(middleware.STAFF_ROLES)
    unit = domain.require_unit(unit_id)
    return response.object_response(public(unit))


@bp.get("/inventory-units")
def list_inventory_units():
    middleware.authenticate(middleware.STAFF_ROLES)
    return common.paged(
        list(db.units.values()),
        filters=("store_id", "replaced_unit_id", "status", "category"),
    )


# ---------------------------------------------------------------------- crews


@bp.post("/stores/<store_id>/delivery-crews")
def create_crew(store_id):
    middleware.authenticate((middleware.PLATFORM_ADMIN, middleware.STORE_MANAGER))
    store = domain.require_store(store_id)
    body = validators.json_body()
    crew_name = validators.string(body, "crew_name", min_len=1, max_len=80)
    certified = validators.boolean(body, "setup_certified", required=False, default=False)
    status = validators.enum(
        body, "status", CREW_STATUSES, required=False, default="ACTIVE"
    )

    crew = base_row()
    crew["store_id"] = store["id"]
    crew["crew_name"] = crew_name
    crew["setup_certified"] = certified
    crew["status"] = status
    db.crews[crew["id"]] = crew
    return response.object_response(public(crew), 201)


@bp.get("/stores/<store_id>/delivery-crews")
def list_crews(store_id):
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.COMPLIANCE_OFFICER,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
            middleware.SERVICE_TECHNICIAN,
        )
    )
    store = domain.require_store(store_id)
    rows = [c for c in db.crews.values() if c["store_id"] == store["id"]]
    return common.paged(rows)
