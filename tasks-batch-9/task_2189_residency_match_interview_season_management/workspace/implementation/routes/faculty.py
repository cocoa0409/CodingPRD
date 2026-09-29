"""The program faculty roster."""

from flask import Blueprint

import serializers
from auth import endpoint
from envelope import object_response
from errors import ApiError
from store import find, insert, must_find, new_row, rows
from validators import body, fk, opt_bool, q_bool, q_str, req_id_list, req_str
from routes.common import keep, listing

bp = Blueprint("faculty", __name__)


@bp.post("/faculty-members")
@endpoint("ProgramCoordinator", "NrmpAdmin")
def create_faculty_member():
    data = body()
    program = fk(data, "program_id", "programs")
    if program is None:
        req_str(data, "program_id")
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    full_name = req_str(data, "full_name")
    is_director = opt_bool(data, "is_program_director", False)
    is_committee = opt_bool(data, "is_committee_member", False)
    conflicts = req_id_list(data, "conflict_applicant_ids", [])
    for applicant_id in conflicts:
        if find("applicants", applicant_id) is None:
            raise ApiError("ERR_RESOURCE_NOT_FOUND")

    row = new_row(
        program_id=program["id"],
        full_name=full_name,
        is_program_director=is_director,
        is_committee_member=is_committee,
        conflict_applicant_ids=list(conflicts),
    )
    insert("faculty_members", row)
    return object_response(serializers.faculty_member(row), 201)


@bp.get("/faculty-members")
@endpoint("ProgramCoordinator", "ProgramDirector", "ComplianceOfficer", "NrmpAdmin")
def list_faculty_members():
    items = rows("faculty_members")
    items = keep(items, "program_id", q_str("program_id"))
    items = keep(items, "is_program_director", q_bool("is_program_director"))
    items = keep(items, "is_committee_member", q_bool("is_committee_member"))
    return listing(items, serializers.faculty_member)


@bp.get("/faculty-members/<faculty_id>")
@endpoint(
    "ProgramCoordinator", "ProgramDirector", "Interviewer", "ComplianceOfficer", "NrmpAdmin"
)
def read_faculty_member(faculty_id):
    return object_response(
        serializers.faculty_member(must_find("faculty_members", faculty_id))
    )
