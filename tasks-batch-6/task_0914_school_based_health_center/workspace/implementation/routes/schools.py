"""School sites and their program posture (PRD 3.1)."""

from flask import Blueprint

import config
import envelope
import store
from errors import ApiError
from fields import Field
from ladder import Op
from services import serialize

bp = Blueprint("schools", __name__)


def _unique_site_code(op):
    site_code = op.body.get("site_code")
    for school in store.DB["schools"].values():
        if school["site_code"] == site_code:
            raise ApiError("ERR_VALIDATION", "site_code must be unique across all school sites.")


@bp.post("/sbhc/schools")
def create_school():
    op = Op("POST /sbhc/schools", ["SbhcAdmin"])
    op.schema(
        [
            Field("name", "string", required=True, min_len=1, max_len=120),
            Field("site_code", "string", required=True, min_len=1, max_len=16),
            Field("sponsor_hospital_name", "string", required=True),
            Field(
                "telehealth_concurrent_capacity",
                "integer",
                minimum=config.MIN_TELEHEALTH_CONCURRENT_CAPACITY,
                maximum=config.MAX_TELEHEALTH_CONCURRENT_CAPACITY,
            ),
        ]
    )
    op.custom(_unique_site_code)
    op.run()

    school = store.new_row(
        "schools",
        {
            "name": op.body["name"],
            "site_code": op.body["site_code"],
            "sponsor_hospital_name": op.body["sponsor_hospital_name"],
            "program_status": "ACTIVE",
            "telehealth_concurrent_capacity": op.field(
                "telehealth_concurrent_capacity", config.DEFAULT_TELEHEALTH_CONCURRENT_CAPACITY
            ),
            "telehealth_booked_minutes_total": 0,
            "suspended_count": 0,
        },
    )
    return envelope.created(serialize.dump(school))


@bp.get("/sbhc/schools/<id>")
def read_school(id):
    op = Op(
        "GET /sbhc/schools/{id}",
        ["SbhcAdmin", "Registrar", "Clinician", "CareCoordinator", "BillingSpecialist"],
    )
    op.path_id("school", "schools", id, "ERR_SCHOOL_NOT_FOUND")
    op.run()
    return envelope.ok(serialize.dump(op.get("school")))


@bp.post("/sbhc/schools/<id>/program-status")
def set_program_status(id):
    op = Op("POST /sbhc/schools/{id}/program-status", ["SbhcAdmin"])
    op.path_id("school", "schools", id, "ERR_SCHOOL_NOT_FOUND")
    op.schema(
        [Field("program_status", "enum", required=True, values=config.PROGRAM_STATUSES)]
    )

    def _state(op):
        school = op.get("school")
        wanted = op.body["program_status"]
        if wanted == school["program_status"]:
            raise ApiError(
                "ERR_INVALID_STATE",
                "The site is already %s." % school["program_status"],
            )

    op.hook(17, _state)
    op.run()

    school = op.get("school")
    wanted = op.body["program_status"]
    if wanted == "SUSPENDED":
        school["program_status"] = "SUSPENDED"
        school["suspended_count"] = school["suspended_count"] + 1
    else:
        school["program_status"] = "ACTIVE"
    store.touch(school)
    return envelope.ok(serialize.dump(school))
