"""QualityInspection endpoints (PRD §3.7).

Inspections carry only id and created_at. The technician who logged repair labour on a
vehicle can never be that vehicle's quality inspector.
"""

from flask import Blueprint

import serializers
from clock import clock
from db import base_row, db, sorted_rows, touch
from errors import api_error, bad_request
from middleware import authenticate
from response import list_response, object_response
from routes.common import get_quality_inspection, get_technician, get_vehicle
from services import aggregates, calculations
from services import posture as posture_service
from services.constants import PANEL_CODES
from validation import (
    json_body,
    pagination,
    paginate,
    query_filter,
    req_enum,
    req_enum_array,
    req_string,
)
from routes.work_tickets import assert_licensed_for_facility, assert_on_site

bp = Blueprint("quality_inspections", __name__)

READ_ROLES = (
    "CatastropheDirector",
    "ShopEstimator",
    "IntakeAdvisor",
    "QualityInspector",
    "CrewCoordinator",
)


@bp.post("/hail-ops/quality-inspections")
def create_quality_inspection():
    principal = authenticate(("QualityInspector",))
    body = json_body()
    vehicle_id = req_string(body, "vehicle_id")
    inspector_technician_id = req_string(body, "inspector_technician_id")
    result = req_enum(body, "result", ("PASS", "FAIL"))
    defect_panel_codes = req_enum_array(body, "defect_panel_codes", PANEL_CODES, default=[])
    if result == "PASS" and defect_panel_codes:
        raise bad_request("defect_panel_codes must be empty on a PASS.")
    if result == "FAIL" and not defect_panel_codes:
        raise bad_request("A FAIL must name at least one defective panel.")

    vehicle = get_vehicle(vehicle_id)
    inspector = get_technician(inspector_technician_id)

    if principal.user_id != inspector_technician_id:
        raise api_error(
            "ERR_IDENTITY_MISMATCH", "An inspector may only record inspections under their own id."
        )

    facility = db.facilities.get(vehicle["facility_id"])
    if facility is not None:
        posture_service.recompute(facility)
    if facility is None or facility["status"] != "COMMISSIONED":
        raise api_error(
            "ERR_FACILITY_NOT_COMMISSIONED",
            "Inspections may only be recorded at a COMMISSIONED site.",
        )
    if vehicle["repair_status"] != "QC_PENDING":
        raise api_error(
            "ERR_INVALID_VEHICLE_REPAIR_STATE",
            "Only a QC_PENDING vehicle may be inspected.",
        )
    for ticket in aggregates.work_tickets_of_vehicle(vehicle["id"]):
        if ticket["technician_id"] == inspector_technician_id:
            raise api_error(
                "ERR_SEGREGATION_OF_DUTIES",
                "The inspector holds a work ticket on the vehicle under inspection.",
            )
    assert_licensed_for_facility(inspector, facility, clock.date())
    assert_on_site(inspector_technician_id, facility["id"])

    if result == "PASS":
        vehicle["repair_status"] = "READY"
        touch(vehicle)
        # CASCADE hop 1: the SUBMITTED ticket set is paid out under both variants.
        tickets = [
            t for t in aggregates.work_tickets_of_vehicle(vehicle["id"])
            if t["status"] == "SUBMITTED"
        ]
        if tickets:
            calculations.crew_pay_split(vehicle, tickets, facility["pay_model"])
            for ticket in tickets:
                ticket["status"] = "APPROVED"
                touch(ticket)
        # CASCADE hop 2 is automatic: technician pay figures are live aggregates.
    else:
        vehicle["rework_count"] = vehicle["rework_count"] + 1
        vehicle["repair_status"] = "QC_FAILED"
        touch(vehicle)

    row = base_row(versioned=False)
    row.update({
        "vehicle_id": vehicle_id,
        "inspector_technician_id": inspector_technician_id,
        "result": result,
        "defect_panel_codes": list(defect_panel_codes),
        "rework_index": vehicle["rework_count"],
        "inspected_at": clock.instant(),
    })
    db.quality_inspections[row["id"]] = row
    posture_service.recompute(facility)
    return object_response(serializers.quality_inspection(row), 201)


@bp.get("/hail-ops/quality-inspections/<identifier>")
def read_quality_inspection(identifier):
    authenticate(READ_ROLES)
    inspection = get_quality_inspection(identifier)
    return object_response(serializers.quality_inspection(inspection))


@bp.get("/hail-ops/quality-inspections")
def list_quality_inspections():
    authenticate(READ_ROLES)
    limit, offset = pagination()

    rows = sorted_rows(list(db.quality_inspections.values()))
    vehicle_id = query_filter("vehicle_id")
    inspector_technician_id = query_filter("inspector_technician_id")
    result = query_filter("result")
    if vehicle_id is not None:
        rows = [r for r in rows if r["vehicle_id"] == vehicle_id]
    if inspector_technician_id is not None:
        rows = [
            r for r in rows if r["inspector_technician_id"] == inspector_technician_id
        ]
    if result is not None:
        rows = [r for r in rows if r["result"] == result]

    page = paginate(rows, limit, offset)
    return list_response(
        [serializers.quality_inspection(r) for r in page], limit, offset, len(rows)
    )
