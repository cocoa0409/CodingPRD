"""The ERAS applicant registry."""

from flask import Blueprint

import serializers
from auth import endpoint
from envelope import object_response
from errors import ApiError
from store import insert, must_find, new_row, rows
from validators import body, opt_bool, opt_str, q_enum, req_enum, req_int, req_str
from routes.common import keep, listing

bp = Blueprint("applicants", __name__)

SCHOOL_TYPES = ("US_MD", "US_DO", "IMG")
VISA_STATUSES = ("US_CITIZEN", "PERMANENT_RESIDENT", "NEEDS_J1", "NEEDS_H1B")


@bp.post("/applicants")
@endpoint("NrmpAdmin")
def create_applicant():
    data = body()
    eras_id = req_str(data, "eras_id")
    full_name = req_str(data, "full_name")
    school = req_enum(data, "medical_school_type", SCHOOL_TYPES)
    visa = req_enum(data, "visa_status", VISA_STATUSES)
    step2 = req_int(data, "step2_score", minimum=1, maximum=300)
    alum = opt_bool(data, "pipeline_program_alum", False)
    group = opt_str(data, "self_identified_group")

    for existing in rows("applicants"):
        if existing["eras_id"] == eras_id:
            raise ApiError("ERR_DUPLICATE_RESOURCE", "eras_id is already registered.")

    row = new_row(
        eras_id=eras_id,
        full_name=full_name,
        medical_school_type=school,
        visa_status=visa,
        step2_score=step2,
        pipeline_program_alum=alum,
        self_identified_group=group,
    )
    insert("applicants", row)
    return object_response(serializers.applicant(row), 201)


@bp.get("/applicants")
@endpoint("NrmpAdmin", "ProgramCoordinator", "ProgramDirector")
def list_applicants():
    items = rows("applicants")
    items = keep(items, "medical_school_type", q_enum("medical_school_type", SCHOOL_TYPES))
    items = keep(items, "visa_status", q_enum("visa_status", VISA_STATUSES))
    return listing(items, serializers.applicant)


@bp.get("/applicants/<applicant_id>")
@endpoint("NrmpAdmin", "ProgramCoordinator", "ProgramDirector", "Applicant")
def read_applicant(applicant_id):
    return object_response(serializers.applicant(must_find("applicants", applicant_id)))
