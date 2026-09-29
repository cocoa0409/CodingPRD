"""Demolition work orders and the compound utility-disconnection parent."""
from decimal import Decimal

from flask import Blueprint

import calc
import lookups
import store
import web
from core import clock_now, fail, fmt_dt, rhu
from web import endpoint

bp = Blueprint("demolition", __name__)


@bp.post("/parcels/<parcel_id>/demolition-work-orders")
@endpoint("SubrecipientCoordinator")
def create_work_order(parcel_id):
    parcel = lookups.get_parcel(parcel_id)
    web.scope_project(parcel["project_id"])
    body = web.get_body()
    contractor_id = web.req_string(body, "contractor_id")
    survey = web.opt_enum(body, "asbestos_survey_status", store.ASBESTOS_STATUSES, "NOT_PERFORMED")
    scheduled_start = web.req_dt(body, "scheduled_start")
    scheduled_end = web.req_dt(body, "scheduled_end")
    if scheduled_end <= scheduled_start:
        web._bad("scheduled_end", "must be strictly after 'scheduled_start'")
    contractor = lookups.get_contractor(contractor_id)

    buffered_start, buffered_end = calc.buffered_window(scheduled_start, scheduled_end)
    conflicts = calc.buffered_conflicts(contractor_id, buffered_start, buffered_end)
    if conflicts >= int(contractor["max_concurrent_work_orders"]):
        fail("ERR_DEMOLITION_WINDOW_CONFLICT")

    record = store.new_record("DemolitionWorkOrder", {
        "parcel_id": parcel_id,
        "contractor_id": contractor_id,
        "asbestos_survey_status": survey,
        "scheduled_start": fmt_dt(scheduled_start),
        "scheduled_end": fmt_dt(scheduled_end),
        "buffered_start": fmt_dt(buffered_start),
        "buffered_end": fmt_dt(buffered_end),
        "required_utility_types": list(store.REQUIRED_UTILITY_TYPES),
        "confirmed_utility_types": [],
        "total_debris_tons": rhu(Decimal(0), 2),
        "recycled_tons": rhu(Decimal(0), 2),
        "diversion_pct": rhu(Decimal(0), 2),
        "disposal_manifest_no": None,
        "disposal_facility_type": None,
        "failed_inspection_count": 0,
        "status": "ISSUED",
    })
    store.work_orders[record["id"]] = record
    calc.recompute_active_work_orders(contractor)
    store.touch(contractor)
    return web.respond_object(record, 201)


@bp.get("/demolition-work-orders")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def list_work_orders():
    parcel_id = web.query_str("parcel_id")
    contractor_id = web.query_str("contractor_id")
    status = web.query_enum("status", store.WORK_ORDER_STATUSES)
    rows = list(store.work_orders.values())
    if parcel_id is not None:
        rows = [r for r in rows if r["parcel_id"] == parcel_id]
    if contractor_id is not None:
        rows = [r for r in rows if r["contractor_id"] == contractor_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return web.list_response(rows)


@bp.get("/demolition-work-orders/<work_order_id>")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def read_work_order(work_order_id):
    return web.respond_object(lookups.get_work_order(work_order_id))


@bp.post("/demolition-work-orders/<work_order_id>/start")
@endpoint("SubrecipientCoordinator")
def start_work_order(work_order_id):
    order = lookups.get_work_order(work_order_id)
    parcel = store.parcels.get(order["parcel_id"])
    web.scope_parcel(parcel)
    contractor = store.contractors.get(order["contractor_id"])
    if order["status"] not in ("UTILITY_HOLD", "READY", "FAILED_INSPECTION"):
        fail("ERR_INVALID_WORK_ORDER_STATE")
    survey = order["asbestos_survey_status"]
    if survey not in ("CLEARED", "ABATED"):
        fail("ERR_ASBESTOS_SURVEY_MISSING")
    if survey == "ABATED" and not (contractor and contractor["asbestos_certified"]):
        fail("ERR_ASBESTOS_SURVEY_MISSING")
    if contractor is None or contractor["status"] != "ACTIVE":
        fail("ERR_CONTRACTOR_SUSPENDED")
    if (order["status"] == "FAILED_INSPECTION"
            and int(order["failed_inspection_count"]) > store.MAX_DEMOLITION_REWORKS):
        fail("ERR_DEMOLITION_REWORK_LIMIT")
    if not calc.utilities_complete(order):
        fail("ERR_UTILITY_DISCONNECT_INCOMPLETE")

    order["status"] = "IN_PROGRESS"
    store.touch(order)
    return web.respond_object(order)


@bp.post("/demolition-work-orders/<work_order_id>/complete")
@endpoint("SubrecipientCoordinator")
def complete_work_order(work_order_id):
    order = lookups.get_work_order(work_order_id)
    parcel = store.parcels.get(order["parcel_id"])
    web.scope_parcel(parcel)
    contractor = store.contractors.get(order["contractor_id"])
    body = web.get_body()
    total_tons = web.decimal_field(body, "total_debris_tons", places=2, minimum=Decimal(0))
    recycled = web.decimal_field(body, "recycled_tons", places=2, minimum=Decimal(0))
    if recycled > total_tons:
        web._bad("recycled_tons", "must not exceed 'total_debris_tons'")
    manifest = web.req_string(body, "disposal_manifest_no")
    facility = web.req_enum(body, "disposal_facility_type", store.DISPOSAL_FACILITY_TYPES)
    if order["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_WORK_ORDER_STATE")

    diversion = calc.debris_diversion_pct(total_tons, recycled)
    if total_tons != 0 and diversion < store.MIN_DIVERSION_PCT:
        fail("ERR_DEBRIS_DIVERSION_BELOW_MINIMUM")

    order["total_debris_tons"] = rhu(total_tons, 2)
    order["recycled_tons"] = rhu(recycled, 2)
    order["diversion_pct"] = diversion
    order["disposal_manifest_no"] = manifest
    order["disposal_facility_type"] = facility
    order["status"] = "COMPLETED"
    store.touch(order)
    if parcel is not None and parcel["acquisition_status"] == "CLOSED":
        parcel["acquisition_status"] = "DEMOLISHED"
        store.touch(parcel)
    if contractor is not None:
        calc.recompute_active_work_orders(contractor)
        store.touch(contractor)
    return web.respond_object(order)


@bp.post("/demolition-work-orders/<work_order_id>/fail-inspection")
@endpoint("ComplianceMonitor")
def fail_inspection(work_order_id):
    order = lookups.get_work_order(work_order_id)
    body = web.get_body()
    web.req_string(body, "inspection_note")
    if order["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_WORK_ORDER_STATE")
    order["status"] = "FAILED_INSPECTION"
    order["failed_inspection_count"] = int(order["failed_inspection_count"]) + 1
    store.touch(order)
    return web.respond_object(order)


# --------------------------------------------------------------------------
# Utility disconnections
# --------------------------------------------------------------------------

@bp.post("/demolition-work-orders/<work_order_id>/utility-disconnections")
@endpoint("SubrecipientCoordinator")
def create_disconnection(work_order_id):
    order = lookups.get_work_order(work_order_id)
    parcel = store.parcels.get(order["parcel_id"])
    web.scope_parcel(parcel)
    body = web.get_body()
    utility_type = web.req_enum(body, "utility_type", store.UTILITY_TYPES)
    provider = web.req_string(body, "provider_name")
    if order["status"] not in ("ISSUED", "UTILITY_HOLD", "READY"):
        fail("ERR_INVALID_WORK_ORDER_STATE")
    existing = calc.work_order_children(work_order_id)
    for child in existing:
        if child["utility_type"] == utility_type:
            fail("ERR_DUPLICATE_UTILITY_TYPE")

    record = store.new_record("UtilityDisconnection", {
        "work_order_id": work_order_id,
        "utility_type": utility_type,
        "provider_name": provider,
        "confirmation_reference": None,
        "resolved_at": None,
        "failed_attempt_count": 0,
        "status": "PENDING",
    })
    store.disconnections[record["id"]] = record
    if not existing and order["status"] == "ISSUED":
        order["status"] = "UTILITY_HOLD"
        store.touch(order)
    return web.respond_object(record, 201)


@bp.get("/utility-disconnections")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def list_disconnections():
    work_order_id = web.query_str("work_order_id")
    utility_type = web.query_enum("utility_type", store.UTILITY_TYPES)
    status = web.query_enum("status", store.DISCONNECTION_STATUSES)
    rows = list(store.disconnections.values())
    if work_order_id is not None:
        rows = [r for r in rows if r["work_order_id"] == work_order_id]
    if utility_type is not None:
        rows = [r for r in rows if r["utility_type"] == utility_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return web.list_response(rows)


@bp.get("/utility-disconnections/<disconnection_id>")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def read_disconnection(disconnection_id):
    return web.respond_object(lookups.get_disconnection(disconnection_id))


@bp.post("/utility-disconnections/<disconnection_id>/resolve")
@endpoint("SubrecipientCoordinator")
def resolve_disconnection(disconnection_id):
    child = lookups.get_disconnection(disconnection_id)
    order = store.work_orders.get(child["work_order_id"])
    parcel = store.parcels.get(order["parcel_id"]) if order else None
    web.scope_parcel(parcel)
    body = web.get_body()
    outcome = web.req_enum(body, "outcome", ["CONFIRMED", "FAILED"])
    reference = web.opt_string(body, "confirmation_reference")
    if outcome == "CONFIRMED" and (reference is None or reference.strip() == ""):
        web._bad("confirmation_reference", "is required when the outcome is CONFIRMED")
    if order is None or order["status"] not in ("UTILITY_HOLD", "READY"):
        fail("ERR_INVALID_DISCONNECTION_STATE")

    previous = child["status"]
    child["resolved_at"] = fmt_dt(clock_now())
    if outcome == "CONFIRMED":
        child["status"] = "CONFIRMED"
        child["confirmation_reference"] = reference
        store.touch(child)
        calc.recompute_confirmed_utilities(order)
        if order["status"] == "UTILITY_HOLD" and calc.utilities_complete(order):
            order["status"] = "READY"
        store.touch(order)
        return web.respond_object(child)

    child["status"] = "FAILED"
    child["failed_attempt_count"] = int(child["failed_attempt_count"]) + 1
    store.touch(child)
    if previous == "CONFIRMED":
        calc.recompute_confirmed_utilities(order)
        if order["status"] == "READY":
            order["status"] = "UTILITY_HOLD"
        store.touch(order)
    return web.respond_object(child)
