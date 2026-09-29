"""Parties and jurisdictions (PRD 3.1)."""

import re

from flask import Blueprint

from db import db, new_row
from errors import invalid_request
from middleware import endpoint
from response import ok_row
from routes.helpers import PARTY_TYPES, get_jurisdiction, get_party, paged
from validation import (
    bool_field,
    enum_field,
    enum_query,
    get_body,
    int_field,
    str_field,
    str_query,
)

bp = Blueprint("reference", __name__)

ALL_ROLES = (
    "ProjectCoordinator",
    "SolarContractor",
    "RoofingContractor",
    "SolarOwner",
    "SystemOwner",
    "AHJInspector",
)

CODE_PATTERN = re.compile(r"^[A-Z0-9]+$")


@bp.route("/reroof/parties", methods=["POST"])
@endpoint("ProjectCoordinator")
def create_party():
    body = get_body()
    name = str_field(body, "name", required=True, max_len=200)
    party_type = enum_field(body, "party_type", PARTY_TYPES, required=True)
    contact_email = str_field(body, "contact_email", required=True)
    if "@" not in contact_email:
        raise invalid_request("field 'contact_email' must contain '@'")
    buffer_minutes = int_field(
        body, "mobilization_buffer_minutes", required=False, default=120,
        minimum=0, maximum=480,
    )
    crew_capacity = int_field(
        body, "daily_crew_capacity", required=False, default=1, minimum=1
    )
    license_number = str_field(body, "license_number", required=False, default=None)

    party = new_row(
        {
            "name": name,
            "party_type": party_type,
            "contact_email": contact_email,
            "mobilization_buffer_minutes": buffer_minutes,
            "daily_crew_capacity": crew_capacity,
            "license_number": license_number,
        }
    )
    db.parties[party["id"]] = party
    return ok_row(party, 201)


@bp.route("/reroof/parties", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_parties():
    party_type = enum_query("party_type", PARTY_TYPES)
    rows = [
        p
        for p in db.parties.values()
        if party_type is None or p["party_type"] == party_type
    ]
    return paged(rows)


@bp.route("/reroof/parties/<party_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def read_party(party_id):
    return ok_row(get_party(party_id))


@bp.route("/reroof/jurisdictions", methods=["POST"])
@endpoint("ProjectCoordinator")
def create_jurisdiction():
    body = get_body()
    name = str_field(body, "name", required=True)
    code = str_field(body, "code", required=True)
    if not CODE_PATTERN.match(code):
        raise invalid_request("field 'code' must be uppercase alphanumeric")
    for existing in db.jurisdictions.values():
        if existing["code"] == code:
            raise invalid_request("field 'code' must be unique across all jurisdictions")
    repermit = bool_field(body, "repermit_required_for_reinstall", required=True)
    reinspection = bool_field(body, "reinspection_required", required=True)
    slots = int_field(body, "inspection_slots_per_day", required=True, minimum=1)
    backlog = int_field(body, "backlog_days", required=True, minimum=0, maximum=90)
    review_days = int_field(body, "permit_review_days", required=True, minimum=1)
    expedite_fee = int_field(
        body, "expedite_fee_cents", required=False, default=0, minimum=0
    )

    jurisdiction = new_row(
        {
            "name": name,
            "code": code,
            "repermit_required_for_reinstall": repermit,
            "reinspection_required": reinspection,
            "inspection_slots_per_day": slots,
            "backlog_days": backlog,
            "permit_review_days": review_days,
            "expedite_fee_cents": expedite_fee,
        },
        common=False,
    )
    db.jurisdictions[jurisdiction["id"]] = jurisdiction
    return ok_row(jurisdiction, 201)


@bp.route("/reroof/jurisdictions", methods=["GET"])
@endpoint("ProjectCoordinator", "AHJInspector")
def list_jurisdictions():
    code = str_query("code")
    rows = [j for j in db.jurisdictions.values() if code is None or j["code"] == code]
    return paged(rows)


@bp.route("/reroof/jurisdictions/<jurisdiction_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def read_jurisdiction(jurisdiction_id):
    return ok_row(get_jurisdiction(jurisdiction_id))
