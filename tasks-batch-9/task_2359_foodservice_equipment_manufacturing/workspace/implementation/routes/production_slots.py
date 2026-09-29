"""ProductionSlot endpoints (PRD Section 3.7)."""
from datetime import timedelta

from flask import Blueprint

import validate
from db import db, insert, touch, ordered
from errors import ApiError
from middleware import authorize
from response import ok, created, ok_list
from routes.helpers import find, filter_by, require_reason
from services import calc, derive

bp = Blueprint("production_slots", __name__)

STATUSES = ("RESERVED", "CONFIRMED", "IN_BUILD", "COMPLETED", "CANCELLED")
ROLES = ("ProductionPlanner", "ChainAdmin", "PlatformAdmin")


@bp.post("/production-slots")
def create_slot():
    authorize("ProductionPlanner", "PlatformAdmin")
    payload = validate.body()
    build_line_id = validate.string_field(payload, "build_line_id")
    site_order_id = validate.string_field(payload, "site_order_id")
    window_start, window_end = validate.window_fields(payload)
    units = validate.int_field(payload, "units", minimum=1)

    site_order = find(db.site_orders, site_order_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")
    line = find(db.build_lines, build_line_id, "ERR_PRODUCTION_RESOURCE_NOT_FOUND")

    config = db.chain_configurations[site_order["chain_configuration_id"]]
    if config["status"] != "RELEASED":
        raise ApiError("ERR_CONFIGURATION_NOT_RELEASED",
                       "the configuration is %s, not RELEASED" % config["status"])

    model = db.equipment_models[config["equipment_model_id"]]
    if model["energy_type"] not in line["supported_energy_types"]:
        raise ApiError("ERR_LINE_ENERGY_INCOMPATIBLE",
                       "the line is not tooled for %s" % model["energy_type"])

    pad = timedelta(hours=calc.CHANGEOVER_BUFFER_HOURS)
    for other in ordered(db.production_slots):
        if other["build_line_id"] != build_line_id:
            continue
        if other["status"] not in ("RESERVED", "CONFIRMED", "IN_BUILD"):
            continue
        padded_start = other["window_start"] - pad
        padded_end = other["window_end"] + pad
        if window_start <= padded_end and window_end >= padded_start:
            raise ApiError("ERR_BUILD_SLOT_OVERLAP",
                           "the interval collides with an existing commitment on this line")

    capacity = line["daily_capacity_units"] * calc.span_days(window_start, window_end)
    if units > capacity:
        raise ApiError("ERR_BUILD_CAPACITY_EXCEEDED",
                       "%d units exceed the line's %d-unit capacity over the interval"
                       % (units, capacity))

    slot = insert(db.production_slots, {
        "build_line_id": build_line_id,
        "site_order_id": site_order_id,
        "window_start": window_start,
        "window_end": window_end,
        "units": units,
        "status": "RESERVED",
    })

    line["committed_units"] += units
    touch(line)

    if site_order["fulfillment_status"] == "PENDING":
        site_order["fulfillment_status"] = "SCHEDULED"
        touch(site_order)
    derive.refresh_site_order(site_order)
    return created(slot)


@bp.get("/production-slots")
def list_slots():
    authorize(*ROLES)
    limit, offset = validate.pagination()
    build_line_id = validate.str_arg("build_line_id")
    site_order_id = validate.str_arg("site_order_id")
    status = validate.enum_arg("status", STATUSES)

    items = ordered(db.production_slots)
    items = filter_by(items, "build_line_id", build_line_id)
    items = filter_by(items, "site_order_id", site_order_id)
    items = filter_by(items, "status", status)
    return ok_list(items, limit, offset)


@bp.get("/production-slots/<slot_id>")
def get_slot(slot_id):
    authorize(*ROLES)
    slot = find(db.production_slots, slot_id, "ERR_PRODUCTION_RESOURCE_NOT_FOUND")
    return ok(slot)


@bp.post("/production-slots/<slot_id>/build-progress")
def build_progress(slot_id):
    authorize("ProductionPlanner", "PlatformAdmin")
    payload = validate.body()
    progress = validate.enum_field(payload, "progress", ("CONFIRM", "START", "COMPLETE"))

    slot = find(db.production_slots, slot_id, "ERR_PRODUCTION_RESOURCE_NOT_FOUND")
    required = {"CONFIRM": "RESERVED", "START": "CONFIRMED", "COMPLETE": "IN_BUILD"}[progress]
    if slot["status"] != required:
        raise ApiError("ERR_PRODUCTION_STATE_INVALID",
                       "%s is not permitted from %s" % (progress, slot["status"]))
    if progress in ("START", "COMPLETE") and db.clock < slot["window_start"]:
        raise ApiError("ERR_PRODUCTION_STATE_INVALID",
                       "the clock has not reached the slot's window_start")

    site_order = db.site_orders[slot["site_order_id"]]
    config = db.chain_configurations[site_order["chain_configuration_id"]]
    # PRD Section 2.9 check 24 guards the whole build-progress endpoint, not just
    # the CONFIRM and START settings spelled out in Section 3.7.
    if config["status"] != "RELEASED":
        raise ApiError("ERR_CONFIGURATION_NOT_RELEASED",
                       "the configuration is %s, not RELEASED" % config["status"])

    if progress == "CONFIRM":
        slot["status"] = "CONFIRMED"
        touch(slot)
    elif progress == "START":
        slot["status"] = "IN_BUILD"
        touch(slot)
        if site_order["fulfillment_status"] == "SCHEDULED":
            site_order["fulfillment_status"] = "IN_BUILD"
        touch(site_order)
    else:
        slot["status"] = "COMPLETED"
        touch(slot)
        line = db.build_lines.get(slot["build_line_id"])
        if line is not None:
            line["committed_units"] -= slot["units"]
            touch(line)
        if site_order["fulfillment_status"] == "IN_BUILD":
            site_order["fulfillment_status"] = "BUILT"
            touch(site_order)

    derive.refresh_site_order(site_order)
    return ok(slot)


@bp.post("/production-slots/<slot_id>/cancellation")
def cancel_slot(slot_id):
    authorize("ProductionPlanner", "PlatformAdmin")
    payload = validate.body()
    require_reason(payload, "cancellation_reason")

    slot = find(db.production_slots, slot_id, "ERR_PRODUCTION_RESOURCE_NOT_FOUND")
    if slot["status"] not in ("RESERVED", "CONFIRMED"):
        raise ApiError("ERR_PRODUCTION_STATE_INVALID",
                       "a %s slot cannot be cancelled" % slot["status"])

    slot["status"] = "CANCELLED"
    touch(slot)

    line = db.build_lines.get(slot["build_line_id"])
    if line is not None:
        line["committed_units"] -= slot["units"]
        touch(line)

    site_order = db.site_orders.get(slot["site_order_id"])
    if site_order is not None:
        if not derive.live_slots_for_site_order(site_order["id"]):
            if site_order["fulfillment_status"] == "SCHEDULED":
                site_order["fulfillment_status"] = "PENDING"
                touch(site_order)
        derive.refresh_site_order(site_order)
    return ok(slot)
