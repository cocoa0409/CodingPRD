"""Rental sets and the copy availability ledger (PRD 3.2)."""
from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_RENTAL_SET_NOT_FOUND,
    ERR_SET_HAS_OPEN_LOANS,
    ERR_WORK_NOT_FOUND,
)
from middleware import require_auth
from response import success_object
from serializers import ser_rental_set
from services import get_or_404, lines_of_set
from util import is_int, is_str, new_record, touch
from routes.helpers import body, paginate, require_fields

bp = Blueprint("rental_sets", __name__)

ALL_ROLES = ("LibraryAdmin", "LibraryClerk", "ReturnsClerk", "BillingManager", "RightsAdvisor", "Customer")
GRADES = ("A", "B", "C", "D")
SET_STATUSES = ("IN_SERVICE", "UNDER_REPAIR", "RETIRED")
_OPEN_LINE_STATUSES = ("RESERVED", "DISPATCHED", "ON_LOAN", "OVERDUE")


@bp.post("/library/rental-sets")
def create_rental_set():
    require_auth("LibraryAdmin")
    data = body()
    require_fields(data, ["work_id", "set_code", "copy_count", "replacement_value_cents"])
    work = db["works"].get(data["work_id"])
    if work is None:
        raise ApiError(ERR_WORK_NOT_FOUND, 404, "Work not found")
    if not is_str(data["set_code"]):
        raise ApiError(ERR_INVALID_REQUEST, 400, "set_code is required")
    if not is_int(data["copy_count"]) or data["copy_count"] < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "copy_count must be an integer >= 1")
    if not is_int(data["replacement_value_cents"]) or data["replacement_value_cents"] <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "replacement_value_cents must be an integer > 0")
    for s in db["rental_sets"].values():
        if s["set_code"] == data["set_code"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, "set_code must be unique across the library")
    rec = new_record()
    rec.update(
        {
            "work_id": work["id"],
            "set_code": data["set_code"],
            "copy_count": data["copy_count"],
            # available_copy_count is computed (ledger); any client-supplied
            # value is ignored. It initializes equal to copy_count.
            "condition_grade": "A",
            "replacement_value_cents": data["replacement_value_cents"],
            "status": "IN_SERVICE",
        }
    )
    db["rental_sets"][rec["id"]] = rec
    return success_object(ser_rental_set(rec), status=201)


@bp.get("/library/rental-sets")
def list_rental_sets():
    require_auth(*ALL_ROLES)
    rows = list(db["rental_sets"].values())
    wid = request.args.get("work_id")
    if wid is not None:
        rows = [s for s in rows if s["work_id"] == wid]
    return paginate(rows, ser_rental_set)


@bp.get("/library/rental-sets/<sid>")
def get_rental_set(sid):
    require_auth(*ALL_ROLES)
    rec = get_or_404("rental_sets", sid, ERR_RENTAL_SET_NOT_FOUND)
    return success_object(ser_rental_set(rec))


@bp.patch("/library/rental-sets/<sid>")
def update_rental_set(sid):
    require_auth("LibraryAdmin")
    rec = get_or_404("rental_sets", sid, ERR_RENTAL_SET_NOT_FOUND)
    data = body()

    new_status = data.get("status")
    new_grade = data.get("condition_grade")
    if new_status is not None and new_status not in SET_STATUSES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid rental set status")
    if new_grade is not None and new_grade not in GRADES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid condition_grade")

    changed = False
    if new_status is not None:
        cur = rec["status"]
        if cur == "IN_SERVICE" and new_status == "UNDER_REPAIR":
            rec["status"] = "UNDER_REPAIR"
        elif cur == "UNDER_REPAIR" and new_status == "IN_SERVICE":
            # Repair complete: lift the recorded grade above D.
            if new_grade is not None:
                rec["condition_grade"] = new_grade
                new_grade = None
            elif rec["condition_grade"] == "D":
                rec["condition_grade"] = "C"
            rec["status"] = "IN_SERVICE"
        elif cur == "IN_SERVICE" and new_status == "RETIRED":
            open_lines = [ln for ln in lines_of_set(rec["id"]) if ln["status"] in _OPEN_LINE_STATUSES]
            if open_lines:
                raise ApiError(ERR_SET_HAS_OPEN_LOANS, 409, "Set has open rental lines")
            rec["status"] = "RETIRED"
        else:
            raise ApiError(ERR_INVALID_STATE, 409, "Illegal rental set status transition")
        changed = True
    if new_grade is not None:
        rec["condition_grade"] = new_grade
        # condition_grade D makes the set unrentable until repaired.
        if new_grade == "D" and rec["status"] == "IN_SERVICE":
            rec["status"] = "UNDER_REPAIR"
        changed = True
    if changed:
        touch(rec)
    return success_object(ser_rental_set(rec))
