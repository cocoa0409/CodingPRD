"""Department endpoints."""
from flask import Blueprint

from db import DB, new_id, next_seq
from errors import ApiError
from middleware import auth
from response import ok
from services import get_department, ser, stamp
from util import as_int, as_str, body, required

bp = Blueprint("departments", __name__)


@bp.post("/departments")
def create_department():
    auth(["DiningAdmin"])
    data = body()
    name = as_str(required(data, "name"), "name")
    code = as_str(required(data, "department_code"), "department_code")
    budget = as_int(required(data, "semester_budget_cents"), "semester_budget_cents")
    if budget < 0:
        raise ApiError("ERR_VALIDATION", 400, "semester_budget_cents must be >= 0")
    for d in DB["departments"].values():
        if d["department_code"] == code:
            raise ApiError(
                "ERR_VALIDATION", 400, "department_code must be unique"
            )
    rec = {
        "id": new_id(),
        "name": name,
        "department_code": code,
        "semester_budget_cents": budget,
        "reserved_cents": 0,
        "committed_cents": 0,
        "spent_cents": 0,
        "available_cents": budget,
        "_seq": next_seq(),
    }
    stamp(rec)
    DB["departments"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@bp.get("/departments/<did>")
def get_one_department(did):
    user_id, role = auth(["DiningAdmin", "HallManager", "ContractManager", "DepartmentUser"])
    # Tier 2 ownership: a DepartmentUser may read only their own department.
    if role == "DepartmentUser" and did != user_id:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "DepartmentUser may only read their own department"
        )
    return ok(ser(get_department(did)))
