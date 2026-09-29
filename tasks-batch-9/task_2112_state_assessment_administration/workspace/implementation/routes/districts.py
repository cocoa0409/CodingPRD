"""Districts (PRD 3.1)."""

from flask import Blueprint

import serialize
from db import create, db
from errors import api_error
from middleware import ALL_ROLES, STATE_OFFICER, endpoint, json_body, resolve
from response import object_response
from validators import string_field

bp = Blueprint("districts", __name__)

DISTRICT_CODE_PATTERN = r"[A-Z]{2}-[0-9]{4}"
STATE_CODE_PATTERN = r"[A-Z]{2}"


@bp.post("/districts")
@endpoint(STATE_OFFICER)
def create_district(actor):
    body = json_body()
    name = string_field(body, "name", min_length=1, max_length=120)
    district_code = string_field(body, "district_code", pattern=DISTRICT_CODE_PATTERN)
    state_code = string_field(body, "state_code", pattern=STATE_CODE_PATTERN)

    # Check 21 — district codes are unique across the entire program.
    for existing in db.districts.values():
        if existing["district_code"] == district_code:
            raise api_error("ERR_DUPLICATE_CODE", "district_code already exists.")

    district = create(
        db.districts,
        {
            "name": name,
            "district_code": district_code,
            "state_code": state_code,
            "replacement_charge_total_cents": 0,
            "security_assessment_cents": 0,
            "open_discrepancy_count": 0,
        },
    )
    return object_response(serialize.district(district), 201)


@bp.get("/districts/<district_id>")
@endpoint(*ALL_ROLES)
def read_district(actor, district_id):
    district = resolve(db.districts, district_id, "ERR_DISTRICT_NOT_FOUND")
    return object_response(serialize.district(district))
