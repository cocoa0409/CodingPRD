"""WorkTicket endpoints (PRD §3.7).

Handing a car to quality control is not an operator action: it is the arithmetic
consequence of the submission that leaves no OPEN ticket on the vehicle.
"""

from flask import Blueprint

import serializers
from clock import parse_date
from db import base_row, db, sorted_rows, touch
from errors import api_error
from middleware import authenticate
from response import list_response, object_response
from routes.common import get_technician, get_vehicle, get_work_ticket
from services import aggregates
from services import posture as posture_service
from validation import (
    json_body,
    pagination,
    paginate,
    query_filter,
    req_int,
    req_number,
    req_string,
)

bp = Blueprint("work_tickets", __name__)

READ_ROLES = (
    "CatastropheDirector",
    "ShopEstimator",
    "IntakeAdvisor",
    "PdrTechnician",
    "QualityInspector",
    "CrewCoordinator",
)


def assert_licensed_for_facility(technician, facility, clock_date):
    expires = parse_date(technician["license_expires_at"])
    if expires is None or expires < clock_date:
        raise api_error(
            "ERR_TECHNICIAN_LICENSE_INVALID",
            "The technician's licence has lapsed against the current clock date.",
        )
    if technician["license_state_code"] != facility["state_code"]:
        raise api_error(
            "ERR_TECHNICIAN_LICENSE_INVALID",
            "The technician is not licensed in the facility's state.",
        )


def assert_on_site(technician_id, facility_id):
    for deployment in aggregates.deployments_of_technician(technician_id):
        if deployment["status"] == "ON_SITE" and deployment["facility_id"] == facility_id:
            return
    raise api_error(
        "ERR_INSPECTOR_NOT_DEPLOYED",
        "The technician has no ON_SITE deployment at this vehicle's facility.",
    )


@bp.post("/hail-ops/work-tickets")
def create_work_ticket():
    principal = authenticate(("PdrTechnician",))
    body = json_body()
    vehicle_id = req_string(body, "vehicle_id")
    technician_id = req_string(body, "technician_id")
    labor_units = req_number(body, "labor_units", minimum=0)
    dents_repaired = req_int(body, "dents_repaired", minimum=0)
    panels_worked = req_int(body, "panels_worked", minimum=0)

    vehicle = get_vehicle(vehicle_id)
    technician = get_technician(technician_id)

    if principal.user_id != technician_id:
        raise api_error(
            "ERR_IDENTITY_MISMATCH", "A technician may only log labour under their own id."
        )

    facility = db.facilities.get(vehicle["facility_id"])
    if facility is not None:
        posture_service.recompute(facility)
    if facility is None or facility["status"] != "COMMISSIONED":
        raise api_error(
            "ERR_FACILITY_NOT_COMMISSIONED", "Labour may only be logged at a COMMISSIONED site."
        )
    if vehicle["repair_status"] != "IN_REPAIR":
        raise api_error(
            "ERR_INVALID_VEHICLE_REPAIR_STATE",
            "Tickets may only be opened against a vehicle IN_REPAIR.",
        )
    from clock import clock

    assert_licensed_for_facility(technician, facility, clock.date())
    if facility["posture"] == "FROZEN":
        raise api_error(
            "ERR_FACILITY_POSTURE_BLOCKED", "A frozen site may not accept new labour."
        )
    assert_on_site(technician_id, facility["id"])

    row = base_row()
    row.update({
        "vehicle_id": vehicle_id,
        "technician_id": technician_id,
        "labor_units": labor_units,
        "dents_repaired": dents_repaired,
        "panels_worked": panels_worked,
        "status": "OPEN",
        "payable_flat_cents": 0,
        "payable_pooled_cents": 0,
        "payable_cents": 0,
        "pay_model_applied": None,
    })
    db.work_tickets[row["id"]] = row
    return object_response(serializers.work_ticket(row), 201)


@bp.get("/hail-ops/work-tickets/<identifier>")
def read_work_ticket(identifier):
    authenticate(READ_ROLES)
    ticket = get_work_ticket(identifier)
    return object_response(serializers.work_ticket(ticket))


@bp.get("/hail-ops/work-tickets")
def list_work_tickets():
    authenticate(READ_ROLES)
    limit, offset = pagination()

    rows = sorted_rows(list(db.work_tickets.values()))
    vehicle_id = query_filter("vehicle_id")
    technician_id = query_filter("technician_id")
    status = query_filter("status")
    if vehicle_id is not None:
        rows = [r for r in rows if r["vehicle_id"] == vehicle_id]
    if technician_id is not None:
        rows = [r for r in rows if r["technician_id"] == technician_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page = paginate(rows, limit, offset)
    return list_response([serializers.work_ticket(r) for r in page], limit, offset, len(rows))


@bp.post("/hail-ops/work-tickets/<identifier>/submit")
def submit_work_ticket(identifier):
    principal = authenticate(("PdrTechnician",))
    ticket = get_work_ticket(identifier)

    if principal.user_id != ticket["technician_id"]:
        raise api_error(
            "ERR_IDENTITY_MISMATCH", "A technician may only submit their own ticket."
        )
    if ticket["status"] != "OPEN":
        raise api_error("ERR_INVALID_LIFECYCLE_STATE", "Only an OPEN ticket may be submitted.")

    vehicle = db.vehicles.get(ticket["vehicle_id"])
    if vehicle is None or vehicle["repair_status"] != "IN_REPAIR":
        raise api_error(
            "ERR_INVALID_LIFECYCLE_STATE",
            "Submission requires the vehicle to still be IN_REPAIR.",
        )
    if not ticket["labor_units"] > 0:
        raise api_error("ERR_ZERO_LABOR_UNITS", "A zero-labour submission is refused.")

    ticket["status"] = "SUBMITTED"
    touch(ticket)

    # The last pencil down hands the car to quality control.
    siblings = aggregates.work_tickets_of_vehicle(vehicle["id"])
    open_count = sum(1 for t in siblings if t["status"] == "OPEN")
    submitted_count = sum(1 for t in siblings if t["status"] == "SUBMITTED")
    if open_count == 0 and submitted_count >= 1:
        vehicle["repair_status"] = "QC_PENDING"
        touch(vehicle)

    return object_response(serializers.work_ticket(ticket))
