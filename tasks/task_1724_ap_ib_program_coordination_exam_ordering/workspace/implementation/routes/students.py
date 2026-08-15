"""Student registry + account statement (PRD 3.3)."""
from flask import Blueprint

from errors import raise_error, ERR_FORBIDDEN
from middleware import get_caller, require_roles
from response import success_object
from services import derived
from services.core import new_record
from services.serialize import serialize_student
from validate import (
    get_body, reject_unknown_fields, req_enum, req_int, req_str, require_path_resource,
)

bp = Blueprint("students", __name__)

SUBGROUPS = ("GEN", "FRL", "IEP", "ELL")


@bp.post("/students")
def create_student():
    require_roles(get_caller(), ["ApCoordinator"])
    body = get_body()
    reject_unknown_fields(body, {"full_name", "grade_level", "subgroup_code"})
    rec = new_record("students", {
        "full_name": req_str(body, "full_name"),
        "grade_level": req_int(body, "grade_level", minimum=9, maximum=12),
        "subgroup_code": req_enum(body, "subgroup_code", SUBGROUPS),
    })
    return success_object(serialize_student(rec), status=201)


@bp.get("/students/<rid>/statement")
def get_statement(rid):
    caller = require_roles(get_caller(), ["ApCoordinator", "Registrar", "Student"])
    student = require_path_resource("students", rid)
    if caller.role == "Student" and caller.user_id != student["id"]:
        raise_error(ERR_FORBIDDEN, "students may only read their own statement")
    balance, projected = derived.student_balances(student["id"])
    return success_object({
        "student_id": student["id"],
        "balance_cents": balance,
        "projected_balance_cents": projected,
        "transcript_posted_count": derived.student_transcript_posted_count(student["id"]),
    })
