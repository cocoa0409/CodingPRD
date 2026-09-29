"""Partner agencies, the truck fleet and the volunteer roster (PRD 3.1, 3.7)."""

from decimal import Decimal

from flask import Blueprint

from auth import authenticate, require_agency_scope, require_self_scope, resolve
from core import COUNTIES
from db import db, new_entity, serialize, crew_of_volunteer
from envelope import object_response
from errors import ApiError
from routes._common import filtered, respond_list
from validation import Field, pagination_params, validate_body

bp = Blueprint("directory", __name__)


# --------------------------------------------------------------------------
# Partner agencies
# --------------------------------------------------------------------------
@bp.route("/agencies", methods=["POST"])
def create_agency():
    authenticate(["PlatformAdmin"])
    payload = validate_body([
        Field("name", "string", min_length=1, max_length=120),
        Field("county", "enum", members=COUNTIES),
        Field("quarterly_voucher_quota", "integer", minimum=1),
    ])
    agency = new_entity(
        name=payload["name"],
        county=payload["county"],
        quarterly_voucher_quota=payload["quarterly_voucher_quota"],
        quota_used=0,
        quota_epoch=1,
        standing="GOOD",
        no_show_credits_owed_cents=0,
    )
    db.agencies[agency["id"]] = agency
    return object_response(serialize(agency), 201)


@bp.route("/agencies/<agency_id>", methods=["GET"])
def get_agency(agency_id):
    actor = authenticate(["PlatformAdmin", "CaseManager"])
    agency = resolve("agency", agency_id)
    require_agency_scope(actor, agency["id"])
    return object_response(serialize(agency))


# --------------------------------------------------------------------------
# Trucks
# --------------------------------------------------------------------------
@bp.route("/trucks", methods=["POST"])
def create_truck():
    authenticate(["PlatformAdmin"])
    payload = validate_body([
        Field("label", "string", min_length=1),
        Field("capacity_cubic_feet", "number", exclusive_minimum=0),
        Field("home_county", "enum", members=COUNTIES),
        Field("crew_minimum", "integer", minimum=1, maximum=4),
    ])
    for existing in db.trucks.values():
        if existing["label"] == payload["label"]:
            raise ApiError("ERR_VALIDATION", "`label` must be unique across trucks.")
    truck = new_entity(
        label=payload["label"],
        capacity_cubic_feet=payload["capacity_cubic_feet"],
        home_county=payload["home_county"],
        crew_minimum=payload["crew_minimum"],
        bed_bug_lockout_until=None,
    )
    db.trucks[truck["id"]] = truck
    return object_response(serialize(truck), 201)


@bp.route("/trucks/<truck_id>", methods=["GET"])
def get_truck(truck_id):
    authenticate(["PlatformAdmin", "DispatchPlanner", "IntakeCoordinator"])
    truck = resolve("truck", truck_id)
    return object_response(serialize(truck))


# --------------------------------------------------------------------------
# Volunteers
# --------------------------------------------------------------------------
@bp.route("/volunteers", methods=["POST"])
def create_volunteer():
    authenticate(["PlatformAdmin"])
    payload = validate_body([
        Field("name", "string", min_length=1),
        Field("county", "enum", members=COUNTIES),
        Field("lift_certified", "boolean", required=False, default=False),
    ])
    volunteer = new_entity(
        name=payload["name"],
        county=payload["county"],
        lift_certified=bool(payload["lift_certified"]),
        reliability_score=Decimal("100.0"),
        assigned_hours_month=Decimal("0.0"),
    )
    db.volunteers[volunteer["id"]] = volunteer
    return object_response(serialize(volunteer), 201)


@bp.route("/volunteers/<volunteer_id>", methods=["GET"])
def get_volunteer(volunteer_id):
    actor = authenticate(["PlatformAdmin", "DispatchPlanner", "Volunteer"])
    volunteer = resolve("volunteer", volunteer_id)
    require_self_scope(actor, volunteer["id"])
    return object_response(serialize(volunteer))


@bp.route("/volunteers/<volunteer_id>/crew-assignments", methods=["GET"])
def list_volunteer_crew_assignments(volunteer_id):
    authenticate(["PlatformAdmin", "DispatchPlanner", "Volunteer"])
    limit, offset = pagination_params()
    volunteer = resolve("volunteer", volunteer_id)
    rows = filtered(crew_of_volunteer(volunteer["id"]), {"status": "status"})
    return respond_list(rows, limit, offset)
