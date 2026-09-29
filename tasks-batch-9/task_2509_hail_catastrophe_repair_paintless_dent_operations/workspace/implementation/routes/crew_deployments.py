"""CrewDeployment endpoints (PRD §3.3)."""

from datetime import timedelta

from flask import Blueprint

import serializers
from clock import clock, parse_date
from db import base_row, db, sorted_rows, touch
from errors import api_error, bad_request
from middleware import authenticate
from response import list_response, object_response
from routes.common import get_crew_deployment, get_facility, get_housing_unit, get_technician
from services import aggregates
from services import posture as posture_service
from services.constants import REST_BUFFER_DAYS
from validation import (
    json_body,
    opt_string,
    pagination,
    paginate,
    query_filter,
    req_date_string,
    req_enum,
    req_string,
)

bp = Blueprint("crew_deployments", __name__)

READ_ROLES = ("CatastropheDirector", "CrewCoordinator", "ShopEstimator", "IntakeAdvisor")


@bp.post("/hail-ops/crew-deployments")
def create_crew_deployment():
    authenticate(("CrewCoordinator",))
    body = json_body()
    technician_id = req_string(body, "technician_id")
    facility_id = req_string(body, "facility_id")
    start_date = req_date_string(body, "start_date")
    end_date = req_date_string(body, "end_date")
    housing_unit_id = opt_string(body, "housing_unit_id")
    start = parse_date(start_date)
    end = parse_date(end_date)
    if start > end:
        raise bad_request("start_date must be no later than end_date.")

    technician = get_technician(technician_id)
    facility = get_facility(facility_id)
    housing_unit = get_housing_unit(housing_unit_id) if housing_unit_id is not None else None
    posture_service.recompute(facility)

    clock_date = clock.date()
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

    _reject_overlap(technician_id, start, end)
    if housing_unit is not None:
        _reject_housing_overflow(housing_unit, start, end)

    row = base_row()
    row.update({
        "technician_id": technician_id,
        "facility_id": facility_id,
        "housing_unit_id": housing_unit_id,
        "start_date": start_date,
        "end_date": end_date,
        "pay_split_pct_snapshot": technician["flat_split_pct"],
        "status": "CONFIRMED",
        "actual_end_date": None,
    })
    db.crew_deployments[row["id"]] = row
    posture_service.recompute(facility)
    return object_response(serializers.crew_deployment(row), 201)


def _reject_overlap(technician_id, start, end):
    """One clear calendar day must separate two deployments of the same technician."""
    buffer_days = timedelta(days=REST_BUFFER_DAYS)
    for existing in aggregates.deployments_of_technician(technician_id):
        if existing["status"] not in ("CONFIRMED", "ON_SITE"):
            continue
        existing_start = parse_date(existing["start_date"])
        existing_end = parse_date(aggregates.effective_end_date(existing))
        if start <= existing_end + buffer_days and end + buffer_days >= existing_start:
            raise api_error(
                "ERR_TECHNICIAN_DEPLOYMENT_OVERLAP",
                "The requested interval collides with another deployment of this technician.",
            )


def _reject_housing_overflow(housing_unit, start, end):
    """Aggregate check on every date of the half-open span [start_date, end_date)."""
    existing = [
        d for d in aggregates.deployments_of_housing_unit(housing_unit["id"])
        if d["status"] in ("CONFIRMED", "ON_SITE")
    ]
    spans = [
        (parse_date(d["start_date"]), parse_date(aggregates.effective_end_date(d)))
        for d in existing
    ]
    day = start
    while day < end:
        occupancy = sum(1 for s, e in spans if s <= day < e)
        if occupancy + 1 > housing_unit["bed_count"]:
            raise api_error(
                "ERR_HOUSING_CAPACITY_EXCEEDED",
                "The housing unit would exceed bed_count on %s." % day.isoformat(),
            )
        day = day + timedelta(days=1)


@bp.get("/hail-ops/crew-deployments/<identifier>")
def read_crew_deployment(identifier):
    authenticate(READ_ROLES)
    deployment = get_crew_deployment(identifier)
    facility = db.facilities.get(deployment["facility_id"])
    if facility is not None:
        posture_service.recompute(facility)
    return object_response(serializers.crew_deployment(deployment))


@bp.get("/hail-ops/crew-deployments")
def list_crew_deployments():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    posture_service.recompute_all()

    rows = sorted_rows(list(db.crew_deployments.values()))
    technician_id = query_filter("technician_id")
    facility_id = query_filter("facility_id")
    housing_unit_id = query_filter("housing_unit_id")
    status = query_filter("status")
    if technician_id is not None:
        rows = [r for r in rows if r["technician_id"] == technician_id]
    if facility_id is not None:
        rows = [r for r in rows if r["facility_id"] == facility_id]
    if housing_unit_id is not None:
        rows = [r for r in rows if r["housing_unit_id"] == housing_unit_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page = paginate(rows, limit, offset)
    return list_response(
        [serializers.crew_deployment(r) for r in page], limit, offset, len(rows)
    )


@bp.post("/hail-ops/crew-deployments/<identifier>/status")
def transition_crew_deployment(identifier):
    authenticate(("CrewCoordinator",))
    body = json_body()
    to_status = req_enum(body, "to_status", ("ON_SITE", "ENDED", "CANCELLED"))
    deployment = get_crew_deployment(identifier)
    facility = db.facilities.get(deployment["facility_id"])
    if facility is not None:
        posture_service.recompute(facility)

    if to_status == "ON_SITE":
        if deployment["status"] != "CONFIRMED":
            raise api_error(
                "ERR_INVALID_LIFECYCLE_STATE", "Arrival requires the deployment to be CONFIRMED."
            )
        if facility is None or facility["status"] not in ("SETUP", "COMMISSIONED"):
            raise api_error(
                "ERR_INVALID_LIFECYCLE_STATE",
                "Arrival requires the facility to be SETUP or COMMISSIONED.",
            )
        technician = db.technicians.get(deployment["technician_id"])
        expires = parse_date(technician["license_expires_at"]) if technician else None
        if expires is None or expires < clock.date():
            raise api_error(
                "ERR_TECHNICIAN_LICENSE_INVALID",
                "The technician's licence has lapsed against the current clock date.",
            )
        deployment["status"] = "ON_SITE"
    elif to_status == "CANCELLED":
        if deployment["status"] != "CONFIRMED":
            raise api_error(
                "ERR_INVALID_LIFECYCLE_STATE",
                "Cancellation requires the deployment to be CONFIRMED.",
            )
        deployment["status"] = "CANCELLED"
    else:
        if deployment["status"] != "ON_SITE":
            raise api_error(
                "ERR_INVALID_LIFECYCLE_STATE", "Ending requires the deployment to be ON_SITE."
            )
        deployment["status"] = "ENDED"
        deployment["actual_end_date"] = clock.date_str()

    touch(deployment)
    if facility is not None:
        posture_service.recompute(facility)
    return object_response(serializers.crew_deployment(deployment))
