"""Shipments, install bookings and the contractor handoff (PRD 3.8)."""

from datetime import timedelta

from flask import Blueprint

import serialize
from db import db, fmt_dt, new_row, occupied_days, rows
from errors import (
    ERR_BOOKING_OUTSIDE_REMODEL_WINDOW,
    ERR_CREW_DAILY_CAPACITY_EXCEEDED,
    ERR_CREW_IDENTITY_MISMATCH,
    ERR_CREW_REGION_NOT_SERVED,
    ERR_DELIVERY_OUTSIDE_REMODEL_WINDOW,
    ERR_HANDOFF_OUTSIDE_BOOKING_WINDOW,
    ERR_INSTALL_BOOKING_NOT_READY,
    ERR_INVALID_INTERVAL,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NO_SHIPPABLE_UNITS,
    ERR_STALE_STORE_PLAN_VERSION,
    fail,
)
from middleware import ALL_ROLES, roles_required, user_id
from response import created, ok, ok_list
from services import (
    crew_bookings,
    get_install_booking,
    get_install_crew,
    get_shipment,
    get_store_plan,
    plan_work_orders,
    recompute_unit_counters,
    shipment_bookings,
    shipment_work_orders,
    touch,
)
from routes.plans import check_no_hold
from validation import (
    filter_enum,
    filter_value,
    get_body,
    paginate,
    pagination,
    req_datetime,
    req_int,
    req_string,
)

bp = Blueprint("logistics", __name__)

SHIPMENT_STATUSES = [
    "STAGED", "LOADED", "IN_TRANSIT", "DELIVERED", "HANDED_OFF", "CANCELLED",
]
BOOKING_STATUSES = ["BOOKED", "RELEASED", "COMPLETED"]
CANCELLABLE = ("STAGED", "LOADED", "IN_TRANSIT")
ADVANCE_CHAIN = {
    "STAGED": "LOADED",
    "LOADED": "IN_TRANSIT",
    "IN_TRANSIT": "DELIVERED",
}


# --------------------------------------------------------------------------
@bp.post("/shipments")
@roles_required("LogisticsCoordinator")
def create_shipment():
    body = get_body()
    store_plan_id = req_string(body, "store_plan_id")
    ship_raw, ship_date = req_datetime(body, "ship_date")
    delivery_raw, delivery_date = req_datetime(body, "delivery_date")
    carrier_code = req_string(body, "carrier_code")
    expected_version = req_int(body, "expected_store_plan_version")

    plan = get_store_plan(store_plan_id)  # rank 6

    if expected_version != plan["version"]:  # rank 8
        fail(ERR_STALE_STORE_PLAN_VERSION,
             "Store plan version is %s, not %s" % (plan["version"], expected_version))

    check_no_hold(plan)  # rank 16

    manifest = [wo for wo in plan_work_orders(store_plan_id) if wo["status"] == "COMPLETE"]
    if len(manifest) == 0:  # rank 27
        fail(ERR_NO_SHIPPABLE_UNITS, "The plan has no COMPLETE unit to load")

    # rank 28
    if delivery_date < plan["_remodel_window_start"] \
            or delivery_date > plan["_remodel_window_end"] \
            or delivery_date < ship_date:
        fail(ERR_DELIVERY_OUTSIDE_REMODEL_WINDOW,
             "delivery_date must sit inside the remodel window and at or after ship_date")

    linear_feet = 0
    for wo in manifest:
        line = db.store_plan_lines.get(wo["store_plan_line_id"])
        linear_feet += line["length_ft"] if line is not None else 0

    row = new_row()
    row.update({
        "store_plan_id": store_plan_id,
        "ship_date": ship_raw,
        "delivery_date": delivery_raw,
        "_ship_date": ship_date,
        "_delivery_date": delivery_date,
        "carrier_code": carrier_code,
        "unit_count": len(manifest),
        "linear_feet": linear_feet,
        "handoff_at": None,
        "received_by_name": None,
        "status": "STAGED",
    })
    db.shipments[row["id"]] = row

    for wo in manifest:
        wo["status"] = "SHIPPED"
        wo["shipment_id"] = row["id"]
        touch(wo)

    recompute_unit_counters(plan)
    if plan["production_status"] == "IN_PRODUCTION" \
            and plan["units_shipped_count"] == plan["unit_count"]:
        plan["production_status"] = "COMPLETE"
    touch(plan)

    return created(serialize.dump("Shipment", row))


@bp.post("/shipments/<shipment_id>/advance")
@roles_required("LogisticsCoordinator")
def advance_shipment(shipment_id):
    get_body()
    shipment = get_shipment(shipment_id)

    nxt = ADVANCE_CHAIN.get(shipment["status"])
    if nxt is None:  # rank 7
        fail(ERR_INVALID_STATE_TRANSITION,
             "A %s shipment cannot be advanced" % shipment["status"])

    shipment["status"] = nxt
    touch(shipment)
    return ok(serialize.dump("Shipment", shipment))


@bp.post("/shipments/<shipment_id>/cancel")
@roles_required("LogisticsCoordinator")
def cancel_shipment(shipment_id):
    body = get_body()
    cancel_reason = req_string(body, "cancel_reason")

    shipment = get_shipment(shipment_id)
    if shipment["status"] not in CANCELLABLE:  # rank 7
        fail(ERR_INVALID_STATE_TRANSITION,
             "A %s shipment cannot be cancelled" % shipment["status"])

    # hop 1
    shipment["status"] = "CANCELLED"
    shipment["cancel_reason"] = cancel_reason
    touch(shipment)

    # hop 2
    for wo in shipment_work_orders(shipment_id):
        if wo["status"] == "SHIPPED":
            wo["status"] = "COMPLETE"
            wo["shipment_id"] = None
            touch(wo)

    # hop 3
    plan = db.store_plans.get(shipment["store_plan_id"])
    left_complete = False
    if plan is not None:
        recompute_unit_counters(plan)
        if plan["production_status"] == "COMPLETE" \
                and plan["units_shipped_count"] < plan["unit_count"]:
            plan["production_status"] = "IN_PRODUCTION"
            left_complete = True
        touch(plan)

    # hops 4 and 5 fire because the plan left production COMPLETE
    if left_complete:
        for booking in shipment_bookings(shipment_id):
            if booking["status"] != "BOOKED":
                continue
            booking["status"] = "RELEASED"
            touch(booking)
            crew = db.install_crews.get(booking["install_crew_id"])
            if crew is not None:
                crew["committed_case_days"] = crew["committed_case_days"] - (
                    booking["cases_committed"] * booking["day_count"]
                )
                touch(crew)

    return ok(serialize.dump("Shipment", shipment))


@bp.post("/shipments/<shipment_id>/handoff")
@roles_required("InstallContractor")
def handoff_shipment(shipment_id):
    shipment = get_shipment(shipment_id)  # rank 5 (needed to evaluate rank 3)

    bookings = shipment_bookings(shipment_id)
    if not any(b["install_crew_id"] == user_id() for b in bookings):  # rank 3
        fail(ERR_CREW_IDENTITY_MISMATCH,
             "The acting crew is not booked on this shipment")

    body = get_body()  # rank 4
    received_by_name = req_string(body, "received_by_name")

    if shipment["status"] != "DELIVERED":  # rank 7
        fail(ERR_INVALID_STATE_TRANSITION,
             "Only a DELIVERED shipment may be handed off")

    booked = [b for b in bookings if b["status"] == "BOOKED"]
    if len(booked) == 0:  # rank 33
        fail(ERR_INSTALL_BOOKING_NOT_READY,
             "No BOOKED install booking exists for this shipment")

    now = db.clock
    mine = [b for b in booked if b["install_crew_id"] == user_id()]
    booking = None
    for candidate in mine + [b for b in booked if b not in mine]:
        if candidate["_start_date"] <= now < candidate["_end_date"]:
            booking = candidate
            break
    if booking is None:  # rank 34
        fail(ERR_HANDOFF_OUTSIDE_BOOKING_WINDOW,
             "The logical clock does not fall inside the booking window")

    stamp = fmt_dt(now)
    shipment["status"] = "HANDED_OFF"
    shipment["handoff_at"] = stamp
    shipment["received_by_name"] = received_by_name
    touch(shipment)

    booking["status"] = "COMPLETED"
    touch(booking)
    crew = db.install_crews.get(booking["install_crew_id"])
    if crew is not None:
        crew["committed_case_days"] = crew["committed_case_days"] - (
            booking["cases_committed"] * booking["day_count"]
        )
        touch(crew)

    for wo in shipment_work_orders(shipment_id):
        wo["warranty_start_date"] = stamp
        wo["_warranty_start_date"] = now
        touch(wo)

    return ok(serialize.dump("Shipment", shipment))


@bp.get("/shipments/<shipment_id>")
@roles_required(*ALL_ROLES)
def read_shipment(shipment_id):
    return ok(serialize.dump("Shipment", get_shipment(shipment_id)))


@bp.get("/shipments")
@roles_required(*ALL_ROLES)
def list_shipments():
    limit, offset = pagination()
    store_plan_id = filter_value("store_plan_id")
    status = filter_enum("status", SHIPMENT_STATUSES)

    items = rows(db.shipments)
    if store_plan_id is not None:
        items = [r for r in items if r["store_plan_id"] == store_plan_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]

    page, total = paginate(items, limit, offset)
    return ok_list(serialize.dump_many("Shipment", page), limit, offset, total)


# --------------------------------------------------------------------------
# install bookings
# --------------------------------------------------------------------------
@bp.post("/install-bookings")
@roles_required("LogisticsCoordinator")
def create_install_booking():
    body = get_body()
    shipment_id = req_string(body, "shipment_id")
    install_crew_id = req_string(body, "install_crew_id")
    start_raw, start_date = req_datetime(body, "start_date")
    end_raw, end_date = req_datetime(body, "end_date")
    cases_committed = req_int(body, "cases_committed", minimum=1)

    shipment = get_shipment(shipment_id)        # rank 6
    crew = get_install_crew(install_crew_id)

    if end_date <= start_date:                  # rank 29
        fail(ERR_INVALID_INTERVAL, "end_date must be strictly after start_date")

    plan = db.store_plans.get(shipment["store_plan_id"])

    # rank 30
    latest_end = plan["_remodel_window_end"] + timedelta(days=1)
    if start_date < shipment["_delivery_date"] or end_date > latest_end:
        fail(ERR_BOOKING_OUTSIDE_REMODEL_WINDOW,
             "The booking must start at or after delivery and end by the day after "
             "the remodel window")

    # rank 31
    if plan["region_code"] not in crew["service_region_codes"]:
        fail(ERR_CREW_REGION_NOT_SERVED,
             "Crew %s does not serve region %s" % (crew["crew_code"], plan["region_code"]))

    # rank 32
    candidate_days = occupied_days(start_date, end_date)
    existing = [b for b in crew_bookings(install_crew_id) if b["status"] == "BOOKED"]
    for day in candidate_days:
        load = cases_committed
        for other in existing:
            if day in occupied_days(other["_start_date"], other["_end_date"]):
                load += other["cases_committed"]
        if load > crew["daily_case_capacity"]:
            fail(ERR_CREW_DAILY_CAPACITY_EXCEEDED,
                 "Crew %s would carry %d cases on %s, above its capacity of %d"
                 % (crew["crew_code"], load, day.isoformat(), crew["daily_case_capacity"]))

    row = new_row()
    row.update({
        "shipment_id": shipment_id,
        "install_crew_id": install_crew_id,
        "start_date": start_raw,
        "end_date": end_raw,
        "_start_date": start_date,
        "_end_date": end_date,
        "cases_committed": cases_committed,
        "day_count": len(candidate_days),
        "status": "BOOKED",
    })
    db.install_bookings[row["id"]] = row

    crew["committed_case_days"] = crew["committed_case_days"] + (
        cases_committed * row["day_count"]
    )
    touch(crew)

    return created(serialize.dump("InstallBooking", row))


@bp.post("/install-bookings/<booking_id>/release")
@roles_required("LogisticsCoordinator")
def release_install_booking(booking_id):
    body = get_body()
    release_reason = req_string(body, "release_reason")

    booking = get_install_booking(booking_id)
    if booking["status"] != "BOOKED":  # rank 7
        fail(ERR_INVALID_STATE_TRANSITION,
             "Only a BOOKED booking may be released")

    booking["status"] = "RELEASED"
    booking["release_reason"] = release_reason
    touch(booking)

    crew = db.install_crews.get(booking["install_crew_id"])
    if crew is not None:
        crew["committed_case_days"] = crew["committed_case_days"] - (
            booking["cases_committed"] * booking["day_count"]
        )
        touch(crew)

    return ok(serialize.dump("InstallBooking", booking))


@bp.get("/install-bookings/<booking_id>")
@roles_required(*ALL_ROLES)
def read_install_booking(booking_id):
    return ok(serialize.dump("InstallBooking", get_install_booking(booking_id)))


@bp.get("/install-bookings")
@roles_required(*ALL_ROLES)
def list_install_bookings():
    limit, offset = pagination()
    shipment_id = filter_value("shipment_id")
    install_crew_id = filter_value("install_crew_id")
    status = filter_enum("status", BOOKING_STATUSES)

    items = rows(db.install_bookings)
    if shipment_id is not None:
        items = [r for r in items if r["shipment_id"] == shipment_id]
    if install_crew_id is not None:
        items = [r for r in items if r["install_crew_id"] == install_crew_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]

    page, total = paginate(items, limit, offset)
    return ok_list(serialize.dump_many("InstallBooking", page), limit, offset, total)
