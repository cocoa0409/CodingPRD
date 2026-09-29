"""Fulfillment centers and pick waves."""

from flask import Blueprint

import clock
import db as store
import serializers
from db import db, new_row, ordered, touch
from errors import ApiError
from middleware import endpoint
from services.gates import must_exist
from response import collection, single
from validation import field, paginate, parse_body, parse_query

bp = Blueprint("fulfillment", __name__)

WAVE_STATUSES = ("PLANNED", "LOCKED", "RELEASED")

CENTER_FIELDS = [
    field("name", "string", required=True),
    field("zone_code", "string", required=True),
    field("daily_pick_capacity_units", "integer", required=True, minimum=1),
    field("freight_cents_per_kit", "integer", required=True, minimum=0),
]

WAVE_FIELDS = [
    field("fulfillment_center_id", "id", required=True),
    field("window_start", "datetime", required=True),
    field("window_end", "datetime", required=True),
    field("planned_capacity_units", "integer", required=True, minimum=1),
]

WAVE_FILTERS = [
    field("fulfillment_center_id", "string"),
    field("status", "enum", values=WAVE_STATUSES),
]


# ------------------------------------------------------------------- centers

@bp.post("/fulfillment-centers")
@endpoint(["FulfillmentOps"])
def create_center():
    body, _ = parse_body(CENTER_FIELDS)
    row = new_row()
    row.update({
        "name": body["name"],
        "zone_code": body["zone_code"],
        "daily_pick_capacity_units": body["daily_pick_capacity_units"],
        "freight_cents_per_kit": body["freight_cents_per_kit"],
    })
    db.fulfillment_centers[row["id"]] = row
    return single(serializers.fulfillment_center(row), 201)


@bp.get("/fulfillment-centers/<fulfillment_center_id>")
@endpoint(["FulfillmentOps", "CampaignManager", "PlatformAdmin"])
def get_center(fulfillment_center_id):
    parse_body([])
    row = must_exist("fulfillment_centers", fulfillment_center_id, "Fulfillment center")
    return single(serializers.fulfillment_center(row))


# ---------------------------------------------------------------------- waves

@bp.post("/fulfillment-waves")
@endpoint(["FulfillmentOps"])
def create_wave():
    body, _ = parse_body(WAVE_FIELDS)

    # rung 6 — the pick window must be strictly increasing
    start = clock.sec(clock.parse(body["window_start"]))
    end = clock.sec(clock.parse(body["window_end"]))
    if not end > start:
        raise ApiError("ERR_WAVE_WINDOW_INVALID",
                       "window_end must be strictly later than window_start")

    center = must_exist("fulfillment_centers", body["fulfillment_center_id"],
                        "Fulfillment center")
    row = new_row()
    row.update({
        "fulfillment_center_id": center["id"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "planned_capacity_units": body["planned_capacity_units"],
        "planned_unit_count": 0,
        "shipped_unit_count": 0,
        "status": "PLANNED",
    })
    db.fulfillment_waves[row["id"]] = row
    return single(serializers.fulfillment_wave(row), 201)


@bp.get("/fulfillment-waves/<fulfillment_wave_id>")
@endpoint(["FulfillmentOps", "CampaignManager", "PlatformAdmin"])
def get_wave(fulfillment_wave_id):
    parse_body([])
    row = must_exist("fulfillment_waves", fulfillment_wave_id, "Fulfillment wave")
    return single(serializers.fulfillment_wave(row))


@bp.get("/fulfillment-waves")
@endpoint(["FulfillmentOps", "CampaignManager", "PlatformAdmin"])
def list_waves():
    query = parse_query(WAVE_FILTERS)
    rows = ordered(db.fulfillment_waves.values())
    if query["fulfillment_center_id"] is not None:
        rows = [r for r in rows
                if r["fulfillment_center_id"] == query["fulfillment_center_id"]]
    if query["status"] is not None:
        rows = [r for r in rows if r["status"] == query["status"]]
    page = paginate(rows, query["limit"], query["offset"])
    return collection([serializers.fulfillment_wave(r) for r in page], len(rows),
                      query["limit"], query["offset"])


@bp.post("/fulfillment-waves/<fulfillment_wave_id>/lock")
@endpoint(["FulfillmentOps"])
def lock_wave(fulfillment_wave_id):
    parse_body([])
    wave = must_exist("fulfillment_waves", fulfillment_wave_id, "Fulfillment wave")
    if wave["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_WAVE_STATE",
                       "Wave status is '%s', not PLANNED" % wave["status"])
    if wave["planned_unit_count"] < 1:
        raise ApiError("ERR_INVALID_WAVE_STATE",
                       "An empty wave cannot be locked")
    wave["status"] = "LOCKED"
    touch(wave)
    return single(serializers.fulfillment_wave(wave))


@bp.post("/fulfillment-waves/<fulfillment_wave_id>/release")
@endpoint(["FulfillmentOps"])
def release_wave(fulfillment_wave_id):
    parse_body([])
    wave = must_exist("fulfillment_waves", fulfillment_wave_id, "Fulfillment wave")
    if wave["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_WAVE_STATE",
                       "Wave status is '%s', not LOCKED" % wave["status"])

    now = clock.now_iso()
    for shipment in store.wave_shipments(wave["id"]):
        if shipment["status"] != "ALLOCATED":
            continue
        shipment["status"] = "SHIPPED"
        shipment["shipped_at"] = now
        for line_id, units in shipment["reserved_line_units"].items():
            line = db.kit_lines.get(line_id)
            if line is None:
                continue
            line["units_reserved"] -= units
            line["units_shipped"] += units
            touch(line)
        touch(shipment)
        enrollment = store.enrollment_of_shipment(shipment)
        if enrollment is not None and enrollment["obligation_status"] == "NONE":
            enrollment["obligation_status"] = "SAMPLE_SENT"
            touch(enrollment)

    wave["shipped_unit_count"] = wave["planned_unit_count"]
    wave["planned_unit_count"] = 0
    wave["status"] = "RELEASED"
    touch(wave)
    return single(serializers.fulfillment_wave(wave))
