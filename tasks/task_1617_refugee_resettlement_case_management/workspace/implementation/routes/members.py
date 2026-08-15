"""HouseholdMember endpoints."""

from flask import Blueprint

from db import store, new_id, stamp_new
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE
from helpers import body_dict, req_string, req_bool, req_enum, req_date
from middleware import authenticate, authorize, CASE_MANAGER
from response import success_object, success_list
from serializers import ser_member
from services import members_of, sorted_records
from routes.cases import get_case_or_404

bp = Blueprint("members", __name__)

RELATIONSHIPS = {"PRINCIPAL", "SPOUSE", "CHILD", "OTHER_RELATIVE"}


@bp.post("/members")
def create_member():
    _uid, role = authenticate()
    authorize(role, {CASE_MANAGER})
    d = body_dict()
    # Priority 3: body FK existence (case_id)
    case_id = req_string(d, "case_id")
    case = store.cases.get(case_id)
    if case is None:
        raise ApiError(ERR_NOT_FOUND, 404, "case_id does not identify an existing case.")
    # Priority 4: schema / field validity
    full_name = req_string(d, "full_name")
    dob = req_date(d, "date_of_birth")
    relationship = req_enum(d, "relationship", RELATIONSHIPS)
    work_eligible = req_bool(d, "work_eligible")
    # Priority 6: members may only be added while the case is PRE_ARRIVAL
    if case["status"] != "PRE_ARRIVAL":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Members may only be added while the case is PRE_ARRIVAL."
        )
    member = {
        "id": new_id(),
        "case_id": case["id"],
        "full_name": full_name,
        "date_of_birth": dob,
        "relationship": relationship,
        "work_eligible": work_eligible,
        "age_at_arrival": None,
        "school_age_at_arrival": None,
    }
    stamp_new(member)
    store.members[member["id"]] = member
    return success_object(ser_member(member), 201)


@bp.get("/cases/<case_id>/members")
def list_members(case_id):
    authenticate()
    case = get_case_or_404(case_id)
    return success_list(sorted_records(members_of(case["id"])), ser_member)
