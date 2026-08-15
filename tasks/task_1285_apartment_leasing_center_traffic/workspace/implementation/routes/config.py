"""Property, Agent, and Floorplan endpoints (leasing configuration)."""
from flask import Blueprint

from db import DB, new_id
from errors import ApiError
from middleware import APPLICANT, AGENT, PM, auth
from response import ok, ok_list
from services import (
    PRORATE_METHODS,
    get_agent,
    get_floorplan,
    get_property,
    ser_agent,
    ser_floorplan,
    ser_property,
    sorted_created,
    stamp,
)
from util import (
    apply_filters,
    as_bool,
    as_enum,
    as_nonneg_int,
    as_str,
    body,
    opt,
    pagination,
    required,
)

bp = Blueprint("config", __name__)

READ_ALL = [PM, AGENT, APPLICANT]
READ_STAFF = [PM, AGENT]


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------
@bp.post("/leasing/properties")
def create_property():
    auth([PM])
    data = body()
    name = as_str(required(data, "name"), "name")
    code = as_str(required(data, "code"), "code")
    response_time_target_minutes = as_nonneg_int(
        opt(data, "response_time_target_minutes", 60), "response_time_target_minutes"
    )
    tour_buffer_minutes = as_nonneg_int(
        opt(data, "tour_buffer_minutes", 15), "tour_buffer_minutes"
    )
    self_guided_window_minutes = as_nonneg_int(
        opt(data, "self_guided_window_minutes", 60), "self_guided_window_minutes"
    )
    max_moveins_per_day = as_nonneg_int(
        opt(data, "max_moveins_per_day", 2), "max_moveins_per_day"
    )
    utility_transfer_required = as_bool(
        opt(data, "utility_transfer_required", True), "utility_transfer_required"
    )
    prorate_method = as_enum(
        opt(data, "prorate_method", "CALENDAR"), "prorate_method", PRORATE_METHODS
    )
    required_addenda = opt(data, "required_addenda", [])
    if not isinstance(required_addenda, list) or not all(
        isinstance(a, str) for a in required_addenda
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "required_addenda must be an array of strings"
        )
    for p in DB["properties"].values():
        if p["code"] == code:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "code must be unique across all properties"
            )
    rec = {
        "id": new_id(),
        "name": name,
        "code": code,
        "response_time_target_minutes": response_time_target_minutes,
        "tour_buffer_minutes": tour_buffer_minutes,
        "self_guided_window_minutes": self_guided_window_minutes,
        "max_moveins_per_day": max_moveins_per_day,
        "utility_transfer_required": utility_transfer_required,
        "prorate_method": prorate_method,
        "required_addenda": list(required_addenda),
    }
    stamp(rec)
    DB["properties"][rec["id"]] = rec
    return ok(ser_property(rec), status=201)


@bp.get("/leasing/properties")
def list_properties():
    auth(READ_ALL)
    limit, offset = pagination()
    items = sorted_created(DB["properties"].values())
    total = len(items)
    return ok_list(
        [ser_property(p) for p in items[offset : offset + limit]], total, limit, offset
    )


@bp.get("/leasing/properties/<pid>")
def get_one_property(pid):
    auth(READ_ALL)
    return ok(ser_property(get_property(pid)))


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
@bp.post("/leasing/agents")
def create_agent():
    auth([PM])
    data = body()
    full_name = as_str(required(data, "full_name"), "full_name")
    email = as_str(required(data, "email"), "email")
    property_id = as_str(required(data, "property_id"), "property_id")
    max_concurrent_tours = as_nonneg_int(
        opt(data, "max_concurrent_tours", 1), "max_concurrent_tours"
    )
    active = as_bool(opt(data, "active", True), "active")
    get_property(property_id)
    rec = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "property_id": property_id,
        "max_concurrent_tours": max_concurrent_tours,
        "active": active,
    }
    stamp(rec)
    DB["agents"][rec["id"]] = rec
    return ok(ser_agent(rec), status=201)


@bp.get("/leasing/agents")
def list_agents():
    auth(READ_STAFF)
    limit, offset = pagination()
    items = apply_filters(DB["agents"].values(), [("property_id", "property_id")])
    items = sorted_created(items)
    total = len(items)
    return ok_list(
        [ser_agent(a) for a in items[offset : offset + limit]], total, limit, offset
    )


@bp.get("/leasing/agents/<aid>")
def get_one_agent(aid):
    auth(READ_STAFF)
    return ok(ser_agent(get_agent(aid)))


# ---------------------------------------------------------------------------
# Floorplans
# ---------------------------------------------------------------------------
@bp.post("/leasing/floorplans")
def create_floorplan():
    auth([PM])
    data = body()
    property_id = as_str(required(data, "property_id"), "property_id")
    name = as_str(required(data, "name"), "name")
    bedrooms = as_nonneg_int(required(data, "bedrooms"), "bedrooms")
    base_rent_cents = as_nonneg_int(required(data, "base_rent_cents"), "base_rent_cents")
    total_units = as_nonneg_int(required(data, "total_units"), "total_units")
    get_property(property_id)
    rec = {
        "id": new_id(),
        "property_id": property_id,
        "name": name,
        "bedrooms": bedrooms,
        "base_rent_cents": base_rent_cents,
        "total_units": total_units,
    }
    stamp(rec)
    DB["floorplans"][rec["id"]] = rec
    return ok(ser_floorplan(rec), status=201)


@bp.get("/leasing/floorplans")
def list_floorplans():
    auth(READ_ALL)
    limit, offset = pagination()
    items = apply_filters(
        DB["floorplans"].values(), [("property_id", "property_id")]
    )
    items = sorted_created(items)
    total = len(items)
    return ok_list(
        [ser_floorplan(f) for f in items[offset : offset + limit]], total, limit, offset
    )


@bp.get("/leasing/floorplans/<fid>")
def get_one_floorplan(fid):
    auth(READ_ALL)
    return ok(ser_floorplan(get_floorplan(fid)))
