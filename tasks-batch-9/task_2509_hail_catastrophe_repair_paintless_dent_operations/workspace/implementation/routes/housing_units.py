"""HousingUnit endpoints (PRD §3.3)."""

from flask import Blueprint

import serializers
from clock import clock
from db import base_row, db
from middleware import authenticate
from response import list_response, object_response
from routes.common import get_facility
from services import aggregates
from services import posture as posture_service
from validation import json_body, pagination, paginate, req_int, req_string

bp = Blueprint("housing_units", __name__)

READ_ROLES = ("CatastropheDirector", "CrewCoordinator", "ShopEstimator", "IntakeAdvisor")


@bp.post("/hail-ops/housing-units")
def create_housing_unit():
    authenticate(("CrewCoordinator",))
    body = json_body()
    facility_id = req_string(body, "facility_id")
    label = req_string(body, "label")
    bed_count = req_int(body, "bed_count", minimum=1)
    nightly_rate_cents = req_int(body, "nightly_rate_cents", minimum=0)

    facility = get_facility(facility_id)
    posture_service.recompute(facility)

    row = base_row()
    row.update({
        "facility_id": facility_id,
        "label": label,
        "bed_count": bed_count,
        "nightly_rate_cents": nightly_rate_cents,
    })
    db.housing_units[row["id"]] = row
    return object_response(serializers.housing_unit(row, clock.date()), 201)


@bp.get("/hail-ops/facilities/<identifier>/housing-units")
def list_facility_housing_units(identifier):
    authenticate(READ_ROLES)
    limit, offset = pagination()
    facility = get_facility(identifier)
    posture_service.recompute(facility)

    rows = aggregates.housing_units_of_facility(facility["id"])
    page = paginate(rows, limit, offset)
    clock_date = clock.date()
    return list_response(
        [serializers.housing_unit(r, clock_date) for r in page], limit, offset, len(rows)
    )
