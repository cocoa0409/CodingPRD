"""Crew bases (PRD 3.2)."""

from flask import Blueprint

import enums
import lookup
import validate
from auth import ROLE_REGIONAL_OPS_CONTROLLER, any_role, require
from db import new_entity, public, store
from errors import fail
from response import object_response
from routes.common import collection_listing

bp = Blueprint("crew_bases", __name__)

LIST_FILTERS = (
    ("agreement_id", "agreement_id", None),
    ("staffing_posture", "staffing_posture", enums.STAFFING_POSTURE),
)


@bp.route("/crew-bases", methods=["POST"])
@require(ROLE_REGIONAL_OPS_CONTROLLER)
def create_crew_base():
    data = validate.body()
    agreement_id = validate.string_field(data, "agreement_id")
    agreement = lookup.reference("agreements", agreement_id)

    station_code = validate.string_field(data, "station_code")
    pilots_required_per_aircraft = validate.int_field(
        data, "pilots_required_per_aircraft", minimum=1)
    aircraft_allocation_cap = validate.int_field(
        data, "aircraft_allocation_cap", minimum=1)

    for base in store.crew_bases.values():
        if (base["agreement_id"] == agreement["id"]
                and base["station_code"] == station_code):
            fail("ERR_DUPLICATE_RESOURCE")

    base = new_entity({
        "agreement_id": agreement["id"],
        "station_code": station_code,
        "pilots_required_per_aircraft": pilots_required_per_aircraft,
        "aircraft_allocation_cap": aircraft_allocation_cap,
        "lifecycle_status": "ACTIVE",
        "line_qualified_pilot_count": 0,
        "in_training_pilot_count": 0,
        "assigned_aircraft_count": 0,
        "required_pilot_count": 0,
        "headcount_shortfall": 0,
        "pipeline_shortfall": 0,
        "staffing_posture": "STAFFED",
        "allocatable_aircraft_count": 0,
    })
    store.crew_bases[base["id"]] = base
    return object_response(public(base), 201)


@bp.route("/crew-bases", methods=["GET"])
@any_role()
def list_crew_bases():
    return collection_listing("crew_bases", LIST_FILTERS)


@bp.route("/crew-bases/<base_id>", methods=["GET"])
@any_role()
def read_crew_base(base_id):
    return object_response(public(lookup.crew_base(base_id)))
