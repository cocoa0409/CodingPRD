"""Student endpoints. PRD §3.1."""

from flask import Blueprint, request, g

from core.auth import require_roles
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, stamp_common, lock
from core.validation import require_body, require_field

from services.relationships import (
    get_district_or_404, get_parent_account_in_district,
    get_student_in_district,
)
from services.views import student_view


bp = Blueprint("students", __name__)


@bp.post("/districts/<district_id>/students")
@require_roles("Parent", "AuditOfficer")
def create_student(district_id):
    with lock():
        get_district_or_404(district_id)
        body = require_body(request)
        parent_account_id = require_field(body, "parent_account_id", kind="string")
        full_name = require_field(body, "full_name", kind="string")
        grade_level = require_field(body, "grade_level", kind="int")
        if grade_level < 0 or grade_level > 12:
            raise_error("ERR_VALIDATION",
                        "grade_level must be in [0, 12]")
        # Cross-aggregate reference: parent_account must live in same district.
        pa = get_parent_account_in_district(district_id, parent_account_id)
        # Parent role can only create students under its own account.
        if g.user_role == "Parent" and g.user_id != parent_account_id:
            raise_error("ERR_FORBIDDEN",
                        "Parent may only create students under their own account")
        s = {
            "district_id": district_id,
            "parent_account_id": parent_account_id,
            "full_name": full_name,
            "grade_level": grade_level,
            "eligibility_tier": "PAID",
            "eligibility_application_id": None,
        }
        stamp_common(s)
        STORE.students[s["id"]] = s
        return success_object(student_view(s), status=201)


@bp.get("/districts/<district_id>/students/<student_id>")
@require_roles("Parent", "DistrictReviewer", "CafeteriaManager", "AuditOfficer")
def get_student(district_id, student_id):
    with lock():
        get_district_or_404(district_id)
        s = get_student_in_district(district_id, student_id)
        # Parent ownership scope.
        if g.user_role == "Parent" and s["parent_account_id"] != g.user_id:
            raise_error("ERR_FORBIDDEN",
                        "Parent may only read students under their own account")
        return success_object(student_view(s))
