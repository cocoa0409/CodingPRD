"""Facility endpoints (PRD §3.2)."""

from flask import Blueprint

import serializers
from clock import clock
from db import base_row, db, sorted_rows, touch
from errors import api_error
from middleware import authenticate
from response import list_response, object_response
from routes.common import get_facility, get_storm_event
from services import calculations
from services import posture as posture_service
from services.constants import PAY_MODELS
from validation import (
    json_body,
    pagination,
    paginate,
    query_filter,
    req_enum,
    req_int,
    req_state_code,
    req_string,
)

bp = Blueprint("facilities", __name__)

READ_ROLES = ("CatastropheDirector", "CrewCoordinator", "ShopEstimator", "IntakeAdvisor")
THROUGHPUT_ROLES = ("CatastropheDirector", "ShopEstimator", "IntakeAdvisor")


@bp.post("/hail-ops/facilities")
def create_facility():
    authenticate(("CatastropheDirector",))
    body = json_body()
    storm_event_id = req_string(body, "storm_event_id")
    name = req_string(body, "name")
    state_code = req_state_code(body, "state_code")
    address = req_string(body, "address")
    staging_slot_count = req_int(body, "staging_slot_count", minimum=1)
    pay_model = req_enum(body, "pay_model", PAY_MODELS)

    event = get_storm_event(storm_event_id)
    if event["status"] not in ("TARGETED", "ACTIVE"):
        raise api_error(
            "ERR_INVALID_STORM_EVENT_STATE",
            "A facility may only be stood up for a TARGETED or ACTIVE event.",
        )

    row = base_row()
    row.update({
        "storm_event_id": storm_event_id,
        "name": name,
        "state_code": state_code,
        "address": address,
        "staging_slot_count": staging_slot_count,
        "pay_model": pay_model,
        "status": "SETUP",
        "posture": "RESTRICTED",
        "warranty_counter": 0,
        "commissioned_at": None,
    })
    db.facilities[row["id"]] = row
    posture_service.recompute(row)
    return object_response(serializers.facility(row), 201)


@bp.get("/hail-ops/facilities/<identifier>")
def read_facility(identifier):
    authenticate(READ_ROLES)
    facility = get_facility(identifier)
    posture_service.recompute(facility)
    return object_response(serializers.facility(facility))


@bp.get("/hail-ops/facilities")
def list_facilities():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    posture_service.recompute_all()

    storm_event_id = query_filter("storm_event_id")
    status = query_filter("status")
    rows = sorted_rows(list(db.facilities.values()))
    if storm_event_id is not None:
        rows = [r for r in rows if r["storm_event_id"] == storm_event_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page = paginate(rows, limit, offset)
    return list_response([serializers.facility(r) for r in page], limit, offset, len(rows))


@bp.post("/hail-ops/facilities/<identifier>/commission")
def commission_facility(identifier):
    authenticate(("CatastropheDirector",))
    facility = get_facility(identifier)
    posture_service.recompute(facility)

    if facility["status"] != "SETUP":
        raise api_error(
            "ERR_INVALID_FACILITY_STATE", "Commissioning requires the facility to be SETUP."
        )
    event = db.storm_events.get(facility["storm_event_id"])
    if event is None or event["status"] not in ("TARGETED", "ACTIVE"):
        raise api_error(
            "ERR_INVALID_STORM_EVENT_STATE",
            "Commissioning requires the parent event to be TARGETED or ACTIVE.",
        )
    clock_date = clock.date()
    if not posture_service.permit_coverage_ok(facility, clock_date):
        raise api_error(
            "ERR_REQUIRED_PERMIT_MISSING",
            "An APPROVED, in-window permit is required for every required permit type.",
        )
    if not _has_licensed_deployment(facility, clock_date):
        raise api_error(
            "ERR_NO_LICENSED_TECHNICIAN",
            "A CONFIRMED or ON_SITE deployment with a licensed technician is required.",
        )

    facility["status"] = "COMMISSIONED"
    facility["commissioned_at"] = clock.instant()
    touch(facility)
    posture_service.recompute(facility)
    return object_response(serializers.facility(facility))


def _has_licensed_deployment(facility, clock_date):
    from clock import parse_date
    from services import aggregates

    for deployment in aggregates.deployments_of_facility(facility["id"]):
        if deployment["status"] not in ("CONFIRMED", "ON_SITE"):
            continue
        technician = db.technicians.get(deployment["technician_id"])
        if technician is None:
            continue
        if technician["license_state_code"] != facility["state_code"]:
            continue
        expires = parse_date(technician["license_expires_at"])
        if expires is None or expires < clock_date:
            continue
        return True
    return False


@bp.get("/hail-ops/facilities/<identifier>/throughput-summary")
def facility_throughput_summary(identifier):
    authenticate(THROUGHPUT_ROLES)
    facility = get_facility(identifier)
    posture_service.recompute(facility)

    occupied, free, ratio = posture_service.staging_counters(facility)
    projection = calculations.facility_throughput_projection(facility)
    from services import aggregates

    data = {
        "staging_slot_count": facility["staging_slot_count"],
        "staging_slots_occupied": occupied,
        "staging_slots_free": free,
        "staging_occupancy_ratio": float(ratio),
        "posture": facility["posture"],
        "open_vehicle_count": projection["open_vehicle_count"],
        "vehicles_in_repair": projection["vehicles_in_repair"],
        "vehicles_ready": projection["vehicles_ready"],
        "released_count": projection["released_count"],
        "on_site_technician_count": projection["on_site_technician_count"],
        "projected_days_to_clear": projection["projected_days_to_clear"],
        "billable_accrued_cents": aggregates.facility_billable_accrued_cents(facility["id"]),
        "absorbed_rental_cents": aggregates.facility_absorbed_rental_cents(facility["id"]),
    }
    return object_response(data)
