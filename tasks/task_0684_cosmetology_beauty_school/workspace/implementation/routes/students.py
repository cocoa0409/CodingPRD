"""Student routes (PRD 3.1; §1.5)."""
from flask import Blueprint

import db
import errors
import helpers
import lookups
import response
from middleware import require

bp = Blueprint("students", __name__)


@bp.post("/school/students")
@require("Registrar")
def create_student():
    data = helpers.body()
    helpers.require_fields(data, "full_name", "email", "ssn_last4")
    full_name = helpers.require_str(data, "full_name")
    email = helpers.require_str(data, "email")
    ssn_last4 = helpers.require_str(data, "ssn_last4")

    # Priority 6: Student.email is unique across all students.
    for s in db.students.values():
        if s["email"] == email:
            raise errors.duplicate_key("email already exists")

    row = {
        "full_name": full_name,
        "email": email,
        "ssn_last4": ssn_last4,
        "status": "PROSPECT",
    }
    db.stamp_new(row)
    db.students[row["id"]] = row
    return response.created(row)


@bp.get("/school/students/<sid>")
@require("Registrar", "FinancialAidOfficer", "Student")
def get_student(sid):
    row = lookups.path(db.students, sid)
    return response.ok(row)
