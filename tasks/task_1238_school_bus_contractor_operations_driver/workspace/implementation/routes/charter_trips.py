"""CharterTrip endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import db
from envelope import success_list, success_object
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_BUS_DISTRICT_MISMATCH,
    ERR_BUS_NOT_IN_SERVICE,
    ERR_BUS_OVERLAP_CONFLICT,
    ERR_CAPACITY_INSUFFICIENT,
    ERR_CHARTER_BUS_UNAVAILABLE,
    ERR_CHARTER_DATE_PAST,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_DISTRICT_CREDIT_HOLD,
    ERR_DRIVER_OVERLAP_CONFLICT,
    ERR_INSPECTION_OVERDUE,
    ERR_INVALID_STATE,
    ERR_INVALID_TIME_RANGE,
    ERR_STALE_VERSION,
    raise_err,
)
from middleware import (
    authenticate,
    district_ownership,
    get_or_404,
    read_scoping,
    require_roles,
)
from services.pricing import (
    bus_assignment_conflicts_for_charter,
    charter_bus_conflict,
    charter_cancel_fee,
    charter_final_price,
    charter_quote_price,
    district_outstanding_balance,
    driver_charter_conflicts,
)
from routes.service_days import check_driver_dispatchable
from validation import (
    get_body,
    opt_str,
    paginate,
    pagination_params,
    req_date,
    req_int,
    req_minute,
    req_str,
)

bp = Blueprint("charter_trips", __name__)

READ_ROLES = {"SystemAdmin", "DistrictAdmin", "ContractorOps", "FinanceClerk", "Driver"}
TERMINAL = ("INVOICED", "DECLINED", "CANCELLED", "EXPIRED")


def check_trip_transition(trip, allowed_from):
    if trip["status"] in TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "CharterTrip is in a terminal state")
    if trip["status"] not in allowed_from:
        raise_err(
            ERR_INVALID_STATE,
            "CharterTrip in state %s cannot perform this transition" % trip["status"],
        )


def owning_contract(trip):
    return get_or_404("contracts", trip["contract_id"], "Contract")


@bp.route("/busops/charter-trips", methods=["POST"])
def create_charter():
    body = get_body()
    contract_id = req_str(body, "contract_id")
    purpose = req_str(body, "purpose")
    trip_date = req_date(body, "trip_date")
    pickup = req_minute(body, "pickup_minute")
    ret = req_minute(body, "return_minute")
    est_hours = req_int(body, "estimated_hours_x10", minimum=0)
    est_miles = req_int(body, "estimated_miles", minimum=0)
    passengers = req_int(body, "passenger_count", minimum=0)
    actor = authenticate()
    require_roles(actor, {"DistrictAdmin"})
    contract = get_or_404("contracts", contract_id, "Contract")
    district_ownership(actor, contract["district_id"])
    # temporal
    if trip_date < db.clock_date().isoformat():
        raise_err(ERR_CHARTER_DATE_PAST, "trip_date is before the logical clock date")
    if ret <= pickup:
        raise_err(ERR_INVALID_TIME_RANGE, "return_minute must be strictly after pickup_minute")
    # fiscal
    if contract["status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_NOT_ACTIVE, "Charter requests require contract ACTIVE")

    rec = {
        "id": db.new_id(),
        "contract_id": contract_id,
        "purpose": purpose,
        "trip_date": trip_date,
        "pickup_minute": pickup,
        "return_minute": ret,
        "estimated_hours_x10": est_hours,
        "estimated_miles": est_miles,
        "passenger_count": passengers,
        "assigned_bus_id": None,
        "assigned_driver_id": None,
        "status": "REQUESTED",
        "quote_price_cents": None,
        "quote_valid_until": None,
        "deposit_cents": None,
        "final_price_cents": None,
        "actual_hours_x10": None,
        "actual_miles": None,
        "cancel_fee_cents": None,
        "refund_cents": None,
        "_quote_valid_until_dt": None,
        "_district_ref": contract["district_id"],
    }
    db.stamp_new(rec)
    db.STORES["charter_trips"][rec["id"]] = rec
    return success_object(db.public(rec), status=201)


@bp.route("/busops/charter-trips", methods=["GET"])
def list_charters():
    limit, offset = pagination_params()
    actor = authenticate()
    require_roles(actor, READ_ROLES)
    items = list(db.all_of("charter_trips"))
    for param in ("contract_id", "assigned_bus_id", "assigned_driver_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [t for t in items if t.get(param) == v]
    page, info = paginate(items, limit, offset)
    return success_list(page, info)


@bp.route("/busops/charter-trips/<rid>", methods=["GET"])
def get_charter(rid):
    actor = authenticate()
    require_roles(actor, READ_ROLES)
    rec = get_or_404("charter_trips", rid, "CharterTrip")
    err = read_scoping(actor, rec)
    if err:
        raise err
    return success_object(db.public(rec))


@bp.route("/busops/charter-trips/<rid>/quote", methods=["POST"])
def quote_charter(rid):
    get_body()
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    trip = get_or_404("charter_trips", rid, "CharterTrip")
    check_trip_transition(trip, ("REQUESTED",))
    contract = owning_contract(trip)
    if contract["status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_NOT_ACTIVE, "Quoting requires contract ACTIVE")
    trip["quote_price_cents"] = charter_quote_price(
        contract, trip["estimated_hours_x10"], trip["estimated_miles"]
    )
    valid_until = db.clock_now() + timedelta(hours=72)
    trip["_quote_valid_until_dt"] = valid_until
    trip["quote_valid_until"] = db.fmt_clock(valid_until)
    trip["status"] = "QUOTED"
    db.touch(trip)
    return success_object(db.public(trip))


@bp.route("/busops/charter-trips/<rid>/approve", methods=["POST"])
def approve_charter(rid):
    body = get_body()
    expected = req_int(body, "expected_charter_trip_version")
    deposit = req_int(body, "deposit_cents", minimum=0)
    actor = authenticate()
    require_roles(actor, {"DistrictAdmin"})
    trip = get_or_404("charter_trips", rid, "CharterTrip")
    contract = owning_contract(trip)
    district_ownership(actor, contract["district_id"])
    if expected != trip["version"]:
        raise_err(
            ERR_STALE_VERSION,
            "expected_charter_trip_version does not match the trip's current version",
        )
    check_trip_transition(trip, ("QUOTED",))
    trip["deposit_cents"] = deposit
    trip["status"] = "APPROVED"
    db.touch(trip)
    return success_object(db.public(trip))


@bp.route("/busops/charter-trips/<rid>/decline", methods=["POST"])
def decline_charter(rid):
    body = get_body()
    opt_str(body, "reason")
    actor = authenticate()
    require_roles(actor, {"DistrictAdmin"})
    trip = get_or_404("charter_trips", rid, "CharterTrip")
    contract = owning_contract(trip)
    district_ownership(actor, contract["district_id"])
    check_trip_transition(trip, ("QUOTED",))
    trip["status"] = "DECLINED"
    db.touch(trip)
    return success_object(db.public(trip))


@bp.route("/busops/charter-trips/<rid>/schedule", methods=["POST"])
def schedule_charter(rid):
    body = get_body()
    bus_id = req_str(body, "assigned_bus_id")
    driver_id = opt_str(body, "assigned_driver_id")
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    trip = get_or_404("charter_trips", rid, "CharterTrip")
    bus = get_or_404("buses", bus_id, "Bus")
    driver = get_or_404("drivers", driver_id, "Driver") if driver_id is not None else None
    contract = owning_contract(trip)

    check_trip_transition(trip, ("APPROVED",))
    # 9. driver dispatchability (when a driver is named)
    if driver is not None:
        check_driver_dispatchable(driver)
    # 10. bus dispatchability
    if bus["status"] != "IN_SERVICE":
        raise_err(ERR_BUS_NOT_IN_SERVICE, "Bus status is not IN_SERVICE")
    due = db.parse_date(bus["next_inspection_due"])
    trip_d = db.parse_date(trip["trip_date"])
    if due is None or trip_d is None or due < trip_d:
        raise_err(
            ERR_INSPECTION_OVERDUE,
            "bus.next_inspection_due must be on or after the trip date",
        )
    if bus["capacity"] < trip["passenger_count"]:
        raise_err(
            ERR_CAPACITY_INSUFFICIENT,
            "bus.capacity is below the charter passenger_count",
        )
    # 11. temporal: buffered-window and overlap checks
    if charter_bus_conflict(
        bus_id, trip["trip_date"], trip["pickup_minute"], trip["return_minute"],
        exclude_trip_id=trip["id"],
    ):
        raise_err(
            ERR_CHARTER_BUS_UNAVAILABLE,
            "Another charter occupies this bus in the buffered window",
        )
    if bus_assignment_conflicts_for_charter(
        bus_id, trip["trip_date"], trip["pickup_minute"], trip["return_minute"]
    ):
        raise_err(
            ERR_BUS_OVERLAP_CONFLICT,
            "A CONFIRMED route assignment intersects the charter's buffered window",
        )
    if driver is not None and driver_charter_conflicts(
        driver_id, trip["trip_date"], trip["pickup_minute"], trip["return_minute"]
    ):
        raise_err(
            ERR_DRIVER_OVERLAP_CONFLICT,
            "Driver has a CONFIRMED assignment overlapping the trip",
        )
    # 13. referential consistency
    if bus["district_id"] != contract["district_id"]:
        raise_err(ERR_BUS_DISTRICT_MISMATCH, "Bus district does not match contract district")
    # 14. fiscal: contract still ACTIVE, then credit hold
    if contract["status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_NOT_ACTIVE, "Scheduling requires contract ACTIVE")
    district = db.find("districts", contract["district_id"])
    outstanding = district_outstanding_balance(contract["district_id"])
    if outstanding + (trip["quote_price_cents"] or 0) > district["credit_limit_cents"]:
        raise_err(
            ERR_DISTRICT_CREDIT_HOLD,
            "District outstanding balance plus quote exceeds the credit limit",
        )

    trip["assigned_bus_id"] = bus_id
    trip["assigned_driver_id"] = driver_id
    trip["status"] = "SCHEDULED"
    db.touch(trip)
    return success_object(db.public(trip))


@bp.route("/busops/charter-trips/<rid>/start", methods=["POST"])
def start_charter(rid):
    get_body()
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    trip = get_or_404("charter_trips", rid, "CharterTrip")
    check_trip_transition(trip, ("SCHEDULED",))
    trip["status"] = "IN_PROGRESS"
    db.touch(trip)
    return success_object(db.public(trip))


@bp.route("/busops/charter-trips/<rid>/complete", methods=["POST"])
def complete_charter(rid):
    body = get_body()
    actual_hours = req_int(body, "actual_hours_x10", minimum=0)
    actual_miles = req_int(body, "actual_miles", minimum=0)
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    trip = get_or_404("charter_trips", rid, "CharterTrip")
    check_trip_transition(trip, ("IN_PROGRESS",))
    contract = owning_contract(trip)
    trip["actual_hours_x10"] = actual_hours
    trip["actual_miles"] = actual_miles
    trip["final_price_cents"] = charter_final_price(
        contract, trip["estimated_hours_x10"], actual_hours, actual_miles
    )
    trip["status"] = "COMPLETED"
    db.touch(trip)
    bus = db.find("buses", trip.get("assigned_bus_id"))
    if bus is not None:
        bus["odometer_miles"] += actual_miles
        db.touch(bus)
    return success_object(db.public(trip))


@bp.route("/busops/charter-trips/<rid>/cancel", methods=["POST"])
def cancel_charter(rid):
    body = get_body()
    opt_str(body, "reason")
    actor = authenticate()
    require_roles(actor, {"DistrictAdmin", "ContractorOps"})
    trip = get_or_404("charter_trips", rid, "CharterTrip")
    contract = owning_contract(trip)
    if actor["role"] == "DistrictAdmin":
        district_ownership(actor, contract["district_id"])
    check_trip_transition(trip, ("REQUESTED", "QUOTED", "APPROVED", "SCHEDULED"))
    if trip["status"] in ("REQUESTED", "QUOTED"):
        fee = 0
        refund = 0
    else:
        fee = charter_cancel_fee(trip, trip["quote_price_cents"] or 0)
        refund = (trip["deposit_cents"] or 0) - fee
    trip["cancel_fee_cents"] = fee
    trip["refund_cents"] = refund
    trip["status"] = "CANCELLED"
    db.touch(trip)
    return success_object(db.public(trip))
