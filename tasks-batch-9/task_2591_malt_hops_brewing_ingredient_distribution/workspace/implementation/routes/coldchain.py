"""Cold storage zones, reefer loads and temperature telemetry (PRD 3.9)."""

from flask import Blueprint, request

from calc import assess_reading, readings_of_shipment, shipments_of_order, zone_admits
from cascades import run_excursion_cascade
from db import by_created, db, new_entity, set_dt, touch
from errors import ApiError
from middleware import ALL_ROLES, require
from response import array_response, object_response
from serialize import reading_out, shipment_out, zone_out
from util import D
from validation import (
    body,
    f_dec,
    f_dt,
    f_int,
    f_str,
    f_version,
    filter_exists,
    must_exist,
    paginate,
    pagination,
)

bp = Blueprint("coldchain", __name__)

RESTAGE_STATUSES = ("STAGED", "HELD")


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

@bp.post("/cold-storage-zones")
def create_zone():
    require(("WarehouseOperator", "PlatformAdmin"))
    payload = body()
    zone_code = f_str(payload, "zone_code", min_len=1, max_len=20)
    setpoint = f_dec(
        payload,
        "temp_setpoint_c",
        required=True,
        scale=2,
        minimum="-40.00",
        maximum="25.00",
    )
    capacity = f_int(payload, "capacity_pallets", required=True, minimum=1)
    tolerance = f_dec(
        payload, "tolerance_c", required=False, scale=2, exclusive_min=0, default=D("2.0")
    )

    # priority 32: zone_code is globally unique
    for existing in db.zones.values():
        if existing["zone_code"] == zone_code:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE_CODE", "zone_code is already commissioned"
            )

    zone = new_entity()
    zone.update(
        {
            "zone_code": zone_code,
            "temp_setpoint_c": setpoint,
            "tolerance_c": tolerance,
            "capacity_pallets": capacity,
            "occupied_pallets": 0,
        }
    )
    db.zones[zone["id"]] = zone
    return object_response(zone_out(zone), 201)


@bp.get("/cold-storage-zones/<zone_id>")
def get_zone(zone_id):
    require(ALL_ROLES)
    zone = must_exist("zones", zone_id)
    return object_response(zone_out(zone))


# ---------------------------------------------------------------------------
# Reefer loads
# ---------------------------------------------------------------------------

@bp.post("/cold-chain-shipments")
def stage_load():
    require(("WarehouseOperator",))
    payload = body()
    order_id = f_str(payload, "sales_order_id", min_len=1)
    zone_id = f_str(payload, "cold_storage_zone_id", min_len=1)
    expected_version = f_version(payload, "expected_sales_order_version")
    pallet_count = f_int(payload, "pallet_count", required=True, minimum=1)
    stage_from, from_raw = f_dt(payload, "stage_from", required=True)
    stage_until, until_raw = f_dt(payload, "stage_until", required=True)
    setpoint = f_dec(
        payload,
        "reefer_setpoint_c",
        required=True,
        scale=2,
        minimum="-40.00",
        maximum="25.00",
    )
    tolerance = f_dec(
        payload,
        "reefer_tolerance_c",
        required=False,
        scale=2,
        exclusive_min=0,
        default=D("2.0"),
    )

    # priority 7: body identifiers, left to right
    order = must_exist("orders", order_id)
    zone = must_exist("zones", zone_id)

    # priority 19: optimistic concurrency on the order
    if int(expected_version) != int(order["version"]):
        raise ApiError(
            "ERR_STALE_SALES_ORDER_VERSION",
            "expected_sales_order_version does not match the order's current version",
        )
    # priority 21: only a cold-chain order may carry a reefer load
    if not order["requires_cold_chain"]:
        raise ApiError(
            "ERR_COLD_CHAIN_NOT_CERTIFIED",
            "The order does not require cold chain handling",
        )
    # priority 26: half-open staging window
    if stage_until <= stage_from:
        raise ApiError(
            "ERR_INVALID_STAGING_WINDOW", "stage_until must be strictly after stage_from"
        )
    # priority 31: aggregate boundary sweep over the zone's STAGED set.  A
    # re-stage releases the prior load's pallets, so they are excluded.
    superseded = [
        s for s in shipments_of_order(order["id"]) if s["status"] in RESTAGE_STATUSES
    ]
    if not zone_admits(
        zone,
        (stage_from, stage_until, pallet_count),
        exclude_ids=tuple(s["id"] for s in superseded),
    ):
        raise ApiError(
            "ERR_ZONE_CAPACITY_EXCEEDED",
            "The staging window would push the zone past capacity_pallets",
        )

    for prior in superseded:
        prior["status"] = "SUPERSEDED"
        touch(prior)

    shipment = new_entity()
    shipment.update(
        {
            "sales_order_id": order["id"],
            "cold_storage_zone_id": zone["id"],
            "pallet_count": pallet_count,
            "reefer_setpoint_c": setpoint,
            "reefer_tolerance_c": tolerance,
            "excursion_minutes": 0,
            "reading_count": 0,
            "last_reading_at": None,
            "status": "STAGED",
        }
    )
    set_dt(shipment, "stage_from", stage_from, from_raw)
    set_dt(shipment, "stage_until", stage_until, until_raw)
    db.shipments[shipment["id"]] = shipment
    touch(order)
    return object_response(shipment_out(shipment), 201)


@bp.get("/cold-chain-shipments/<shipment_id>")
def get_load(shipment_id):
    require(ALL_ROLES)
    shipment = must_exist("shipments", shipment_id)
    return object_response(shipment_out(shipment))


@bp.get("/cold-chain-shipments")
def list_loads():
    require(ALL_ROLES)
    limit, offset = pagination()
    order_id = request.args.get("sales_order_id")
    zone_id = request.args.get("cold_storage_zone_id")
    status = request.args.get("status")
    filter_exists("orders", order_id)
    filter_exists("zones", zone_id)

    items = []
    for shipment in db.shipments.values():
        if order_id and shipment["sales_order_id"] != order_id:
            continue
        if zone_id and shipment["cold_storage_zone_id"] != zone_id:
            continue
        if status and shipment["status"] != status:
            continue
        items.append(shipment)
    items = by_created(items)
    page = paginate(items, limit, offset)
    return array_response([shipment_out(s) for s in page], len(items), limit, offset)


@bp.post("/cold-chain-shipments/<shipment_id>/depart")
def depart_load(shipment_id):
    require(("WarehouseOperator",))
    body()
    shipment = must_exist("shipments", shipment_id)
    # priority 17
    if shipment["status"] != "STAGED":
        raise ApiError(
            "ERR_INVALID_SHIPMENT_STATE", "Only a STAGED load may depart the zone"
        )
    order = db.orders.get(shipment["sales_order_id"])
    # priority 46: a picked order with an approved credit decision
    if (
        order is None
        or order["fulfillment_status"] != "PICKED"
        or order["credit_status"] != "APPROVED"
    ):
        raise ApiError(
            "ERR_ORDER_CREDIT_NOT_APPROVED",
            "Departure requires a PICKED order with an APPROVED credit decision",
        )

    shipment["status"] = "IN_TRANSIT"
    touch(shipment)
    return object_response(shipment_out(shipment))


@bp.post("/cold-chain-shipments/<shipment_id>/release-hold")
def release_hold(shipment_id):
    require(("CreditManager",))
    body()
    shipment = must_exist("shipments", shipment_id)
    # priority 17
    if shipment["status"] != "HELD":
        raise ApiError(
            "ERR_INVALID_SHIPMENT_STATE", "Only a HELD load may be returned to staging"
        )
    zone = db.zones[shipment["cold_storage_zone_id"]]
    # priority 31: re-test the zone over the load's original window
    if not zone_admits(
        zone,
        (shipment["stage_from"], shipment["stage_until"], shipment["pallet_count"]),
        exclude_ids=(shipment["id"],),
    ):
        raise ApiError(
            "ERR_ZONE_CAPACITY_EXCEEDED",
            "The zone filled up while the load was held",
        )
    order = db.orders.get(shipment["sales_order_id"])
    # priority 46
    if order is None or order["credit_status"] != "APPROVED":
        raise ApiError(
            "ERR_ORDER_CREDIT_NOT_APPROVED",
            "The order's credit decision must be APPROVED again",
        )

    shipment["status"] = "STAGED"
    touch(shipment)
    return object_response(shipment_out(shipment))


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

@bp.post("/cold-chain-shipments/<shipment_id>/readings")
def append_reading(shipment_id):
    require(("WarehouseOperator",))
    payload = body()
    temp_c = f_dec(
        payload, "temp_c", required=True, scale=2, minimum="-60.00", maximum="60.00"
    )
    recorded_at, recorded_raw = f_dt(payload, "recorded_at", required=True)

    shipment = must_exist("shipments", shipment_id)
    # priority 17: a flagged load stops accumulating
    if shipment["status"] != "IN_TRANSIT":
        raise ApiError(
            "ERR_INVALID_SHIPMENT_STATE",
            "Readings may only be appended to an IN_TRANSIT load",
        )
    # priority 25: the series is append-only
    last = shipment.get("last_reading_at")
    if last is not None and recorded_at < last:
        raise ApiError(
            "ERR_READING_OUT_OF_ORDER",
            "recorded_at must be at or after the load's last_reading_at",
        )

    series = readings_of_shipment(shipment["id"])
    previous = series[-1] if series else None

    reading = new_entity(with_version=False)
    reading.update(
        {
            "cold_chain_shipment_id": shipment["id"],
            "temp_c": temp_c,
            "interval_minutes": 0,
            "in_violation": False,
            "cumulative_excursion_minutes": 0,
        }
    )
    set_dt(reading, "recorded_at", recorded_at, recorded_raw)
    flagged = assess_reading(shipment, reading, previous)
    db.readings[reading["id"]] = reading

    shipment["excursion_minutes"] = reading["cumulative_excursion_minutes"]
    shipment["reading_count"] = int(shipment["reading_count"]) + 1
    set_dt(shipment, "last_reading_at", recorded_at, recorded_raw)
    if flagged:
        # CASCADE C link 1
        shipment["status"] = "EXCURSION_FLAGGED"
    touch(shipment)
    if flagged:
        # CASCADE C links 2 and 3
        run_excursion_cascade(shipment)
    return object_response(reading_out(reading), 201)


@bp.get("/cold-chain-shipments/<shipment_id>/readings")
def list_readings(shipment_id):
    require(ALL_ROLES)
    limit, offset = pagination()
    shipment = must_exist("shipments", shipment_id)
    items = readings_of_shipment(shipment["id"])
    page = paginate(items, limit, offset)
    return array_response([reading_out(r) for r in page], len(items), limit, offset)
