"""Trucks, white-glove crews, floor zones and pickup jobs (PRD 3.1, 3.4, 3.6)."""

from flask import Blueprint

import auth
import calc
import envelope
import serializers as ser
import services
import store
import validation as v
from errors import fail
from store import db

bp = Blueprint("logistics", __name__)

ZONE_TYPES = ("SHOWROOM_FRONT", "SHOWROOM_REAR", "WAREHOUSE", "CLEARANCE")


# ---------------------------------------------------------------------------
# trucks
# ---------------------------------------------------------------------------
@bp.post("/trucks")
def create_truck():
    auth.require("LogisticsCoordinator")
    data = v.body()
    name = v.req_str(data, "name")
    capacity = v.req_int(data, "capacity_volume_cuft", minimum=1)
    row = store.new_row(
        db.trucks, {"name": name, "capacity_volume_cuft": capacity, "status": "AVAILABLE"}
    )
    return envelope.created(ser.truck(row))


@bp.get("/trucks/<truck_id>")
def get_truck(truck_id):
    auth.require("LogisticsCoordinator", "GalleryManager")
    row = v.lookup(db.trucks, truck_id, "ERR_TRUCK_NOT_FOUND")
    return envelope.ok(ser.truck(row))


@bp.get("/trucks")
def list_trucks():
    auth.require("LogisticsCoordinator", "GalleryManager")
    limit, offset = v.pagination()
    status = v.q("status")
    rows = store.ordered(db.trucks)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page = v.window(rows, limit, offset)
    return envelope.listing(ser.many(ser.truck, page), limit, offset, len(rows))


# ---------------------------------------------------------------------------
# white-glove crews
# ---------------------------------------------------------------------------
@bp.post("/white-glove-crews")
def create_crew():
    auth.require("LogisticsCoordinator")
    data = v.body()
    name = v.req_str(data, "name")
    max_concurrent_jobs = v.req_int(data, "max_concurrent_jobs", minimum=1)
    row = store.new_row(
        db.crews,
        {"name": name, "max_concurrent_jobs": max_concurrent_jobs, "status": "AVAILABLE"},
    )
    return envelope.created(ser.crew(row))


@bp.get("/white-glove-crews/<crew_id>")
def get_crew(crew_id):
    auth.require("LogisticsCoordinator", "GalleryManager")
    row = v.lookup(db.crews, crew_id, "ERR_CREW_NOT_FOUND")
    return envelope.ok(ser.crew(row))


@bp.get("/white-glove-crews")
def list_crews():
    auth.require("LogisticsCoordinator", "GalleryManager")
    limit, offset = v.pagination()
    status = v.q("status")
    rows = store.ordered(db.crews)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page = v.window(rows, limit, offset)
    return envelope.listing(ser.many(ser.crew, page), limit, offset, len(rows))


# ---------------------------------------------------------------------------
# floor zones
# ---------------------------------------------------------------------------
@bp.post("/floor-zones")
def create_zone():
    auth.require("FloorOperator", "GalleryManager")
    data = v.body()
    name = v.req_str(data, "name")
    zone_type = v.req_enum(data, "zone_type", ZONE_TYPES)
    capacity_sqft = v.req_int(data, "capacity_sqft", minimum=1)
    row = store.new_row(
        db.zones,
        {
            "name": name,
            "zone_type": zone_type,
            "capacity_sqft": capacity_sqft,
            "status": "OPEN",
        },
    )
    return envelope.created(ser.zone(row))


@bp.get("/floor-zones/<zone_id>")
def get_zone(zone_id):
    auth.require("FloorOperator", "GalleryManager", "SystemOperator")
    row = v.lookup(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    return envelope.ok(ser.zone(row))


@bp.get("/floor-zones")
def list_zones():
    auth.require("FloorOperator", "GalleryManager", "SystemOperator")
    limit, offset = v.pagination()
    zone_type = v.q("zone_type")
    status = v.q("status")
    rows = store.ordered(db.zones)
    if zone_type is not None:
        rows = [r for r in rows if r["zone_type"] == zone_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page = v.window(rows, limit, offset)
    return envelope.listing(ser.many(ser.zone, page), limit, offset, len(rows))


@bp.post("/floor-zones/<zone_id>/close")
def close_zone(zone_id):
    auth.require("GalleryManager")
    row = v.lookup(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    if row["status"] == "CLOSED":
        fail("ERR_ZONE_CLOSED")
    row["status"] = "CLOSED"
    store.touch(row)
    return envelope.ok(ser.zone(row))


@bp.get("/floor-zones/<zone_id>/shrinkage-audits")
def list_zone_audits(zone_id):
    auth.require("FloorOperator", "GalleryManager", "SystemOperator")
    v.lookup(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    limit, offset = v.pagination()
    status = v.q("status")
    rows = [a for a in store.ordered(db.shrinkage_audits) if a["floor_zone_id"] == zone_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    page = v.window(rows, limit, offset)
    return envelope.listing(ser.many(ser.shrinkage_audit, page), limit, offset, len(rows))


# ---------------------------------------------------------------------------
# pickup jobs
# ---------------------------------------------------------------------------
def _quote(job):
    consignor = db.consignors.get(job["consignor_id"])
    items = services.items_of_job(job["id"])
    job["quoted_surcharge_cents"] = calc.pickup_surcharge(
        items, job["declared_stair_flights"], job["declared_elevator"], job["crew_size"]
    )
    return consignor


@bp.post("/pickup-jobs")
def create_pickup_job():
    user_id, role = auth.require("LogisticsCoordinator")
    data = v.body()

    raw_consignor = v.raw_fk(data, "consignor_id")
    if raw_consignor is not None and raw_consignor not in db.consignors:
        fail("ERR_CONSIGNOR_NOT_FOUND")
    raw_truck = v.raw_fk(data, "truck_id")
    if raw_truck is not None and raw_truck not in db.trucks:
        fail("ERR_TRUCK_NOT_FOUND")
    raw_items = data.get("item_ids")
    if isinstance(raw_items, list):
        for entry in raw_items:
            if isinstance(entry, str) and entry.strip() and entry not in db.items:
                fail("ERR_ITEM_NOT_FOUND")

    consignor_id = v.req_id(data, "consignor_id")
    truck_id = v.req_id(data, "truck_id")
    window_start = v.req_dt(data, "window_start")
    window_end = v.req_dt(data, "window_end")
    crew_size = v.req_int(data, "crew_size", minimum=2, maximum=6)
    item_ids = v.opt_id_list(data, "item_ids") or []

    consignor = db.consignors.get(consignor_id)
    if consignor is None:
        fail("ERR_CONSIGNOR_NOT_FOUND")
    truck = db.trucks.get(truck_id)
    if truck is None:
        fail("ERR_TRUCK_NOT_FOUND")

    items = []
    for item_id in item_ids:
        item = db.items.get(item_id)
        if item is None:
            fail("ERR_ITEM_NOT_FOUND")
        if item["lifecycle_state"] != "SCREEN_ACCEPTED" or item["pickup_job_id"] is not None:
            fail("ERR_ITEM_STATE_INVALID")
        items.append(item)

    # ladder 21: the 45-minute turnaround buffer against every other live job
    for other in db.pickup_jobs.values():
        if other["truck_id"] != truck_id or other["status"] != "SCHEDULED":
            continue
        if window_start < store.add_seconds(
            other["window_end"], calc.TURNAROUND_SECONDS
        ) and other["window_start"] < store.add_seconds(window_end, calc.TURNAROUND_SECONDS):
            fail("ERR_TRUCK_WINDOW_CONFLICT")

    # ladder 23
    if not window_start < window_end:
        fail("ERR_WINDOW_ORDER_INVALID")

    if consignor["has_elevator"]:
        declared_stair_flights = 0
    else:
        declared_stair_flights = max(int(consignor["floor_number"]) - 1, 0)

    row = store.new_row(
        db.pickup_jobs,
        {
            "consignor_id": consignor_id,
            "truck_id": truck_id,
            "window_start": window_start,
            "window_end": window_end,
            "crew_size": crew_size,
            "declared_stair_flights": declared_stair_flights,
            "declared_elevator": bool(consignor["has_elevator"]),
            "quoted_surcharge_cents": 0,
            "actual_stair_flights": None,
            "actual_elevator_used": None,
            "actual_crew_size": None,
            "final_surcharge_cents": None,
            "surcharge_variance_cents": None,
            "status": "SCHEDULED",
            "scheduled_by_user_id": user_id,
        },
    )
    for item in items:
        item["lifecycle_state"] = "SCHEDULED_PICKUP"
        item["pickup_job_id"] = row["id"]
        store.touch(item)
    _quote(row)
    return envelope.created(ser.pickup_job(row))


@bp.get("/pickup-jobs/<job_id>")
def get_pickup_job(job_id):
    user_id, role = auth.require("LogisticsCoordinator", "GalleryManager", "Consignor")
    row = v.lookup(db.pickup_jobs, job_id, "ERR_PICKUP_JOB_NOT_FOUND")
    auth.scope_consignor(role, user_id, row["consignor_id"])
    return envelope.ok(ser.pickup_job(row))


@bp.get("/pickup-jobs")
def list_pickup_jobs():
    auth.require("LogisticsCoordinator", "GalleryManager")
    limit, offset = v.pagination()
    rows = store.ordered(db.pickup_jobs)
    for field in ("consignor_id", "truck_id", "status"):
        wanted = v.q(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    page = v.window(rows, limit, offset)
    return envelope.listing(ser.many(ser.pickup_job, page), limit, offset, len(rows))


@bp.post("/pickup-jobs/<job_id>/items")
def attach_item(job_id):
    auth.require("LogisticsCoordinator")
    job = v.lookup(db.pickup_jobs, job_id, "ERR_PICKUP_JOB_NOT_FOUND")
    data = v.body()

    raw_item = v.raw_fk(data, "item_id")
    if raw_item is not None and raw_item not in db.items:
        fail("ERR_ITEM_NOT_FOUND")
    item_id = v.req_id(data, "item_id")
    item = db.items.get(item_id)
    if item is None:
        fail("ERR_ITEM_NOT_FOUND")

    if job["status"] != "SCHEDULED":
        fail("ERR_PICKUP_JOB_STATE_INVALID")
    if item["lifecycle_state"] != "SCREEN_ACCEPTED" or item["pickup_job_id"] is not None:
        fail("ERR_ITEM_STATE_INVALID")
    if item["condition_grade"] == "REJECTED":
        fail("ERR_GRADE_REJECTED")

    truck = db.trucks.get(job["truck_id"])
    projected = services.job_total_volume(job["id"]) + int(item["volume_cuft"])
    if truck is not None and projected > int(truck["capacity_volume_cuft"]):
        fail("ERR_TRUCK_CAPACITY_EXCEEDED")

    item["lifecycle_state"] = "SCHEDULED_PICKUP"
    item["pickup_job_id"] = job["id"]
    store.touch(item)
    _quote(job)
    store.touch(job)
    return envelope.ok(ser.pickup_job(job))


@bp.post("/pickup-jobs/<job_id>/complete")
def complete_pickup_job(job_id):
    auth.require("LogisticsCoordinator")
    job = v.lookup(db.pickup_jobs, job_id, "ERR_PICKUP_JOB_NOT_FOUND")
    data = v.body()
    actual_stair_flights = v.req_int(data, "actual_stair_flights", minimum=0)
    actual_elevator_used = v.req_bool(data, "actual_elevator_used")
    actual_crew_size = v.req_int(data, "actual_crew_size", minimum=2, maximum=6)

    if job["status"] != "SCHEDULED":
        fail("ERR_PICKUP_JOB_STATE_INVALID")
    items = services.items_of_job(job["id"])
    if not items:
        fail("ERR_PICKUP_JOB_STATE_INVALID")

    job["actual_stair_flights"] = actual_stair_flights
    job["actual_elevator_used"] = actual_elevator_used
    job["actual_crew_size"] = actual_crew_size
    final = calc.pickup_surcharge(
        items, actual_stair_flights, actual_elevator_used, actual_crew_size
    )
    job["final_surcharge_cents"] = final
    job["surcharge_variance_cents"] = final - int(job["quoted_surcharge_cents"] or 0)

    if actual_crew_size < int(job["crew_size"]) - 1:
        job["status"] = "FAILED"
        store.touch(job)
        return envelope.ok(ser.pickup_job(job))

    job["status"] = "COMPLETED"
    for item in items:
        item["lifecycle_state"] = "RECEIVED"
        item["inventory_state"] = "IN_CUSTODY"
        store.touch(item)
    consignor = db.consignors.get(job["consignor_id"])
    if consignor is not None:
        services.mint_entry(
            consignor,
            "PICKUP_SURCHARGE_DEBIT",
            -final,
            "pickup surcharge settled on job %s" % job["id"],
            item_id=None,
        )
    store.touch(job)
    return envelope.ok(ser.pickup_job(job))


@bp.post("/pickup-jobs/<job_id>/cancel")
def cancel_pickup_job(job_id):
    auth.require("LogisticsCoordinator")
    job = v.lookup(db.pickup_jobs, job_id, "ERR_PICKUP_JOB_NOT_FOUND")
    if job["status"] != "SCHEDULED":
        fail("ERR_PICKUP_JOB_STATE_INVALID")
    for item in services.items_of_job(job["id"]):
        item["lifecycle_state"] = "SCREEN_ACCEPTED"
        item["pickup_job_id"] = None
        store.touch(item)
    job["status"] = "CANCELLED"
    store.touch(job)
    return envelope.ok(ser.pickup_job(job))
