"""Transport crews, transport jobs, delay notices (PRD 3.6)."""

from flask import Blueprint, request

import calc
from db import bump, clock, create_record, store
from errors import fail
from middleware import ALL_ROLES, require
from response import ok, ok_list
from services import (crew_window_has_capacity, get_or_404,
                      maybe_chain_titled_on_set_complete, record_delay_notice,
                      recompute_delay_compensation, recompute_transport_charge,
                      ser, ser_crew, latest_open_evaluation)
from validate import Shape, get_body, pagination_params

bp = Blueprint("transport", __name__)

ORIGINS = ["FACTORY", "DEALER_LOT"]
DELAY_REASONS = ["WEATHER", "PERMIT_HOLD", "FACTORY_DELAY", "SITE_NOT_READY",
                 "ESCORT_UNAVAILABLE"]


def _list(rows, filters):
    limit, offset = pagination_params()
    rows = [r for r in rows if all(r.get(k) == v for k, v in filters.items())]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    return ok_list([ser(r) for r in rows[offset:offset + limit]], total, limit, offset)


# ------------------------------------------------------------------- crews --

@bp.post("/transport-crews")
@require("DealershipAdmin")
def create_crew(actor_id, actor_role):
    shape = Shape(get_body())
    shape.req_str("name")
    shape.req_int("crew_size", minimum=1)
    shape.req_bool("can_set_multiwide")
    shape.req_int("max_sections_per_window", minimum=1)
    shape.raise_if_errors()
    rec = create_record(store.transport_crews, {
        "name": shape.value("name"),
        "crew_size": shape.value("crew_size"),
        "can_set_multiwide": shape.value("can_set_multiwide"),
        "max_sections_per_window": shape.value("max_sections_per_window"),
    })
    return ok(ser_crew(rec), 201)


@bp.get("/transport-crews/<rid>")
@require(*ALL_ROLES)
def get_crew(rid, actor_id, actor_role):
    crew = get_or_404(store.transport_crews, rid, "ERR_TRANSPORT_CREW_NOT_FOUND",
                      "Transport crew")
    return ok(ser_crew(crew))


# -------------------------------------------------------------------- jobs --

@bp.post("/sales-orders/<rid>/transport-jobs")
@require("TransportCoordinator")
def create_transport_job(rid, actor_id, actor_role):
    order = get_or_404(store.sales_orders, rid, "ERR_SALES_ORDER_NOT_FOUND", "Sales order")
    shape = Shape(get_body())
    shape.req_str("home_unit_id")
    shape.req_str("crew_id")
    shape.req_enum("origin", ORIGINS)
    shape.req_int("distance_miles", minimum=0)
    shape.req_dt("scheduled_start_date")
    shape.req_int("escort_vehicle_count", minimum=0)
    # (5) body foreign-key existence
    unit = crew = None
    if shape.ok("home_unit_id"):
        unit = store.home_units.get(shape.value("home_unit_id"))
        if unit is None:
            fail("ERR_HOME_UNIT_NOT_FOUND", "Home unit not found")
    if shape.ok("crew_id"):
        crew = store.transport_crews.get(shape.value("crew_id"))
        if crew is None:
            fail("ERR_TRANSPORT_CREW_NOT_FOUND", "Transport crew not found")
    # (7) state precondition: order must be FINANCING_APPROVED
    if order["deal_status"] != "FINANCING_APPROVED":
        fail("ERR_INVALID_STATE", "Transport may be booked only for a FINANCING_APPROVED order")
    model = store.home_models.get(unit["model_id"]) if unit is not None else None
    sections = model["section_count"] if model is not None else None
    required_escorts = calc.escort_required_count(model["width_ft"]) if model is not None else 0
    # (9) escort compliance
    if model is not None and shape.ok("escort_vehicle_count"):
        if shape.value("escort_vehicle_count") < required_escorts:
            fail("ERR_ESCORT_REQUIRED",
                 "escort_vehicle_count below the required count for the model's width")
    # (14) crew capability
    if crew is not None and sections is not None and sections >= 2 \
            and not crew["can_set_multiwide"]:
        fail("ERR_CREW_CAPABILITY_INSUFFICIENT",
             "Crew is not certified for multi-section sets")
    # (15) crew window capacity
    if crew is not None and sections is not None and shape.ok("scheduled_start_date"):
        if not crew_window_has_capacity(crew, shape.value("scheduled_start_date"), sections):
            fail("ERR_CREW_WINDOW_CONFLICT",
                 "Crew section capacity exceeded on a date of the move window")
    # (22) no past scheduling
    if shape.ok("scheduled_start_date"):
        if shape.value("scheduled_start_date").date() < clock.now().date():
            fail("ERR_SCHEDULE_IN_PAST", "scheduled_start_date precedes the current clock date")
    # (29) unit-order coherence
    if unit is not None and unit["id"] != order["home_unit_id"]:
        fail("ERR_UNIT_ORDER_MISMATCH", "home_unit_id must equal the order's unit")
    shape.raise_if_errors()

    escort_required = required_escorts > 0
    quoted = calc.transport_quote_cents(
        sections, shape.value("distance_miles"), shape.value("escort_vehicle_count"),
        escort_required, shape.value("scheduled_start_date"))
    rec = create_record(store.transport_jobs, {
        "sales_order_id": order["id"],
        "home_unit_id": unit["id"],
        "crew_id": crew["id"],
        "origin": shape.value("origin"),
        "distance_miles": shape.value("distance_miles"),
        "scheduled_start_date": shape.value("scheduled_start_date"),
        "sections_count": sections,
        "escort_required": escort_required,
        "escort_vehicle_count": shape.value("escort_vehicle_count"),
        "quoted_cost_cents": quoted,
        "status": "SCHEDULED",
        "buyer_notified_at": None,
    })
    order["transport_charge_cents"] = quoted
    bump(order)
    return ok(ser(rec), 201)


@bp.get("/sales-orders/<rid>/transport-jobs")
@require(*ALL_ROLES)
def list_order_transport_jobs(rid, actor_id, actor_role):
    order = get_or_404(store.sales_orders, rid, "ERR_SALES_ORDER_NOT_FOUND", "Sales order")
    return _list([j for j in store.transport_jobs.values()
                  if j["sales_order_id"] == order["id"]], {})


@bp.get("/transport-jobs/<rid>")
@require(*ALL_ROLES)
def get_transport_job(rid, actor_id, actor_role):
    return ok(ser(get_or_404(store.transport_jobs, rid, "ERR_TRANSPORT_JOB_NOT_FOUND",
                             "Transport job")))


@bp.get("/transport-jobs")
@require(*ALL_ROLES)
def list_transport_jobs(actor_id, actor_role):
    filters = {}
    for k in ("home_unit_id", "crew_id", "status"):
        if request.args.get(k) is not None:
            filters[k] = request.args.get(k)
    return _list(store.transport_jobs.values(), filters)


def _get_job(rid):
    return get_or_404(store.transport_jobs, rid, "ERR_TRANSPORT_JOB_NOT_FOUND",
                      "Transport job")


@bp.post("/transport-jobs/<rid>/dispatch")
@require("TransportCoordinator")
def dispatch_job(rid, actor_id, actor_role):
    job = _get_job(rid)
    # (7) state + dispatch window: clock date in [start, start + sections days)
    if job["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "Only a SCHEDULED job can be dispatched")
    window = calc.window_dates(job["scheduled_start_date"], job["sections_count"])
    if clock.now().date() not in window:
        fail("ERR_INVALID_STATE", "Current clock date is outside the scheduled window")
    job["status"] = "EN_ROUTE"
    bump(job)
    unit = store.home_units.get(job["home_unit_id"])
    if unit is not None and unit["status"] == "RESERVED":
        unit["status"] = "IN_TRANSIT"
        bump(unit)
    return ok(ser(job))


@bp.post("/transport-jobs/<rid>/delay")
@require("TransportCoordinator")
def delay_job(rid, actor_id, actor_role):
    job = _get_job(rid)
    # (7) state precondition
    if job["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "Only a SCHEDULED job can be delayed")
    shape = Shape(get_body())
    shape.req_enum("reason", DELAY_REASONS)
    shape.req_dt("new_scheduled_start_date")
    shape.req_bool("buyer_notified")
    # (26) delay notification: a slip of more than 3 whole days needs notice
    if shape.ok("new_scheduled_start_date"):
        slip = calc.whole_delay_days(job["scheduled_start_date"],
                                     shape.value("new_scheduled_start_date"))
        if slip > 3 and shape.ok("buyer_notified") and not shape.value("buyer_notified"):
            fail("ERR_DELAY_NOTIFICATION_REQUIRED",
                 "Delays longer than 3 days require buyer notification")
    # field shape: the new start must be strictly after the current start
    if shape.ok("new_scheduled_start_date"):
        if not shape.value("new_scheduled_start_date") > job["scheduled_start_date"]:
            shape._err("new_scheduled_start_date",
                       "must be strictly after the current scheduled_start_date")
    shape.raise_if_errors()
    new_start = shape.value("new_scheduled_start_date")
    order = store.sales_orders.get(job["sales_order_id"])
    record_delay_notice(job["id"], None, shape.value("reason"),
                        job["scheduled_start_date"], new_start,
                        shape.value("buyer_notified"))
    if shape.value("buyer_notified"):
        job["buyer_notified_at"] = clock.now()
    job["scheduled_start_date"] = new_start
    job["status"] = "DELAYED"
    bump(job)
    if order is not None:
        recompute_delay_compensation(order)
        bump(order)
    return ok(ser(job))


@bp.post("/transport-jobs/<rid>/reschedule")
@require("TransportCoordinator")
def reschedule_job(rid, actor_id, actor_role):
    job = _get_job(rid)
    # (7) state precondition
    if job["status"] != "DELAYED":
        fail("ERR_INVALID_STATE", "Only a DELAYED job can be rescheduled")
    shape = Shape(get_body())
    shape.req_dt("new_scheduled_start_date")
    # (15) crew window capacity for the new window (excluding this job)
    if shape.ok("new_scheduled_start_date"):
        crew = store.transport_crews.get(job["crew_id"])
        if crew is not None and not crew_window_has_capacity(
                crew, shape.value("new_scheduled_start_date"), job["sections_count"],
                exclude_job_id=job["id"]):
            fail("ERR_CREW_WINDOW_CONFLICT",
                 "Crew section capacity exceeded on a date of the new window")
    # (22) no past scheduling
    if shape.ok("new_scheduled_start_date"):
        if shape.value("new_scheduled_start_date").date() < clock.now().date():
            fail("ERR_SCHEDULE_IN_PAST", "new_scheduled_start_date precedes the current clock date")
    shape.raise_if_errors()
    job["scheduled_start_date"] = shape.value("new_scheduled_start_date")
    job["status"] = "SCHEDULED"
    bump(job)
    return ok(ser(job))


@bp.post("/transport-jobs/<rid>/deliver")
@require("TransportCoordinator")
def deliver_job(rid, actor_id, actor_role):
    job = _get_job(rid)
    if job["status"] != "EN_ROUTE":
        fail("ERR_INVALID_STATE", "Only an EN_ROUTE job can be delivered")
    order = store.sales_orders.get(job["sales_order_id"])
    unit = store.home_units.get(job["home_unit_id"])
    job["status"] = "DELIVERED"
    bump(job)
    if unit is not None and unit["status"] == "IN_TRANSIT":
        unit["status"] = "ON_SITE"
        unit["delivered_at"] = clock.now()
        if order is not None and order["placement_type"] == "COMMUNITY_LOT":
            unit["lot_id"] = order.get("lot_id")
        bump(unit)
    if order is not None and order["placement_type"] == "COMMUNITY_LOT" and order.get("lot_id"):
        lot = store.lots.get(order["lot_id"])
        if lot is not None and lot["status"] == "RESERVED":
            lot["status"] = "LEASED"
            bump(lot)
    if order is not None and order["deal_status"] == "AWAITING_DELIVERY":
        order["deal_status"] = "DELIVERED"
        bump(order)
    return ok(ser(job))


@bp.post("/transport-jobs/<rid>/complete-set")
@require("InstallationManager")
def complete_set(rid, actor_id, actor_role):
    job = _get_job(rid)
    # (7) state precondition
    if job["status"] != "DELIVERED":
        fail("ERR_INVALID_STATE", "Only a DELIVERED job can complete the set")
    order = store.sales_orders.get(job["sales_order_id"])
    # (10) set permit: latest non-SUPERSEDED evaluation APPROVED with a permit
    ev = latest_open_evaluation(order["id"]) if order is not None else None
    if ev is None or ev["status"] != "APPROVED" or not ev.get("permit_number"):
        fail("ERR_PERMIT_MISSING",
             "Set completion requires an approved evaluation carrying a permit number")
    unit = store.home_units.get(job["home_unit_id"])
    job["status"] = "SET_COMPLETE"
    bump(job)
    if unit is not None and unit["status"] == "ON_SITE":
        unit["status"] = "INSTALLED"
        unit["set_completed_at"] = clock.now()
        bump(unit)
    if order is not None and order["deal_status"] == "DELIVERED":
        order["deal_status"] = "SET_COMPLETE"
        maybe_chain_titled_on_set_complete(order)
        bump(order)
    return ok(ser(job))


@bp.post("/transport-jobs/<rid>/cancel")
@require("TransportCoordinator")
def cancel_job(rid, actor_id, actor_role):
    job = _get_job(rid)
    if job["status"] not in ("SCHEDULED", "DELAYED"):
        fail("ERR_INVALID_STATE", "Only a SCHEDULED or DELAYED job can be cancelled")
    job["status"] = "CANCELLED"
    bump(job)
    order = store.sales_orders.get(job["sales_order_id"])
    if order is not None:
        before = order["transport_charge_cents"]
        recompute_transport_charge(order)
        if order["transport_charge_cents"] != before:
            bump(order)
    return ok(ser(job))


# ------------------------------------------------------------ delay notices --

@bp.post("/sales-orders/<rid>/delay-notices")
@require("SalesConsultant")
def create_order_delay_notice(rid, actor_id, actor_role):
    order = get_or_404(store.sales_orders, rid, "ERR_SALES_ORDER_NOT_FOUND", "Sales order")
    shape = Shape(get_body())
    shape.req_enum("reason", DELAY_REASONS)
    shape.req_dt("original_date")
    shape.req_dt("new_date")
    shape.req_bool("buyer_notified")
    if shape.ok("original_date") and shape.ok("new_date"):
        if not shape.value("new_date") > shape.value("original_date"):
            shape._err("new_date", "must be after original_date")
    shape.raise_if_errors()
    rec = record_delay_notice(None, order["id"], shape.value("reason"),
                              shape.value("original_date"), shape.value("new_date"),
                              shape.value("buyer_notified"))
    recompute_delay_compensation(order)
    bump(order)
    return ok(ser(rec), 201)


@bp.get("/transport-jobs/<rid>/delay-notices")
@require(*ALL_ROLES)
def list_job_delay_notices(rid, actor_id, actor_role):
    job = _get_job(rid)
    return _list([n for n in store.delay_notices.values()
                  if n["transport_job_id"] == job["id"]], {})


@bp.get("/sales-orders/<rid>/delay-notices")
@require(*ALL_ROLES)
def list_order_delay_notices(rid, actor_id, actor_role):
    order = get_or_404(store.sales_orders, rid, "ERR_SALES_ORDER_NOT_FOUND", "Sales order")
    return _list([n for n in store.delay_notices.values()
                  if n["sales_order_id"] == order["id"]], {})
