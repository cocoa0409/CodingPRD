import re

from flask import Blueprint

import find
import serialize
import validators as v
from auth import endpoint
from envelope import object_response, paginate
from store import db, new_record, sorted_records

bp = Blueprint("schools", __name__)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
ROLES = ["CorpsDirector", "TourManager", "MembershipCoordinator", "BusinessManager"]


@bp.route("/host-schools", methods=["POST"])
@endpoint(["TourManager"])
def create_school():
    body = v.get_body()
    name = v.req_str(body, "name")
    city = v.req_str(body, "city")
    state_code = v.req_str(body, "state_code")
    sleeping_space_count = v.req_int(body, "sleeping_space_count")
    capacity_per_space = v.req_int(body, "capacity_per_space")
    rehearsal_field_count = v.req_int(body, "rehearsal_field_count")
    has_air_conditioning = v.req_bool(body, "has_air_conditioning")
    v.check(bool(STATE_CODE_RE.match(state_code)), "state_code",
            "must be exactly two uppercase letters")
    v.check(rehearsal_field_count >= 0, "rehearsal_field_count", "must be at least 0")
    # Rung 6 -- the space count and the per-space capacity must each be >= 1.
    v.positive(sleeping_space_count >= 1, "sleeping_space_count must be at least 1.")
    v.positive(capacity_per_space >= 1, "capacity_per_space must be at least 1.")

    record = new_record()
    record.update({
        "name": name,
        "city": city,
        "state_code": state_code,
        "sleeping_space_count": sleeping_space_count,
        "capacity_per_space": capacity_per_space,
        "rehearsal_field_count": rehearsal_field_count,
        "has_air_conditioning": has_air_conditioning,
    })
    db.schools[record["id"]] = record
    return object_response(serialize.school(record), 201)


@bp.route("/host-schools/<host_school_id>", methods=["GET"])
@endpoint(ROLES)
def get_school(host_school_id):
    return object_response(serialize.school(find.school(host_school_id)))


@bp.route("/host-schools", methods=["GET"])
@endpoint(ROLES)
def list_schools():
    state_code = v.arg_str("state_code")
    records = []
    for record in sorted_records(db.schools):
        if state_code is not None and record["state_code"] != state_code:
            continue
        records.append(record)
    return paginate(records, serialize.school)
