"""Instructor routes (PRD 3.1; §1.5)."""
from flask import Blueprint

import db
import errors
import helpers
import lookups
import response
from middleware import require

bp = Blueprint("instructors", __name__)


@bp.post("/school/instructors")
@require("Registrar")
def create_instructor():
    data = helpers.body()
    helpers.require_fields(data, "full_name", "license_number", "license_expires_on")
    full_name = helpers.require_str(data, "full_name")
    license_number = helpers.require_str(data, "license_number")
    license_expires_on = helpers.require_dt(data, "license_expires_on")
    active = helpers.opt_bool(data, "active", True)

    # Priority 6: Instructor.license_number is unique across all instructors.
    for i in db.instructors.values():
        if i["license_number"] == license_number:
            raise errors.duplicate_key("license_number already exists")

    row = {
        "full_name": full_name,
        "license_number": license_number,
        "license_expires_on": db.iso(license_expires_on),
        "active": active,
    }
    db.stamp_new(row)
    db.instructors[row["id"]] = row
    return response.created(row)


@bp.get("/school/instructors/<iid>")
@require("Registrar", "FinancialAidOfficer", "Instructor", "Student")
def get_instructor(iid):
    row = lookups.path(db.instructors, iid)
    return response.ok(row)
