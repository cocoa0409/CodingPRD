"""ScheduleOfValues endpoints."""
from flask import Blueprint

from db import DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    ensure_sub_not_terminal,
    get_bid,
    get_project,
    get_sov,
    get_subcontract,
    package_of,
    ser_sov,
    sorted_created,
    sov_allocate,
    stamp,
    touch,
)
from util import as_int, as_list, as_str, body, pagination_args, required

bp = Blueprint("sov", __name__)


def _validate_lines(value):
    lines = as_list(value, "lines")
    for i, line in enumerate(lines):
        if not isinstance(line, dict):
            raise ApiError("ERR_VALIDATION", 422, f"lines[{i}] must be an object")
        as_str(required(line, "wbs_code"), "wbs_code")
        as_str(required(line, "description"), "description")
        as_int(required(line, "weight_numerator"), "weight_numerator")
    return lines


def _apply_allocation(sov, sub, lines):
    allocations = sov_allocate(lines, sub["contract_value_cents"])
    stored = []
    for line, allocated in zip(lines, allocations):
        stored.append(
            {
                "wbs_code": line["wbs_code"],
                "description": line["description"],
                "weight_numerator": line["weight_numerator"],
                "allocated_amount_cents": allocated,
            }
        )
    sov["lines"] = stored


@bp.post("/subcontracts/<sub_id>/schedule-of-values")
def create_sov(sub_id):
    auth(["BuyoutLead"])
    sub = get_subcontract(sub_id)
    data = body()
    lines = _validate_lines(required(data, "lines"))
    ensure_sub_not_terminal(sub)
    if sub["status"] not in ("ISSUED", "EXECUTED"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            409,
            "Subcontract not in ISSUED or EXECUTED",
        )
    bid = get_bid(sub["source_bid_id"])
    if bid["status"] == "WITHDRAWN":
        raise ApiError(
            "ERR_BID_WITHDRAWN_SOV_BLOCKED",
            409,
            "SOV creation blocked because the source bid is WITHDRAWN",
        )
    if any(
        s["subcontract_id"] == sub["id"] and s["status"] != "REJECTED"
        for s in DB["schedule_of_values"].values()
    ):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            409,
            "A subcontract carries at most one active (non-REJECTED) schedule",
        )
    rec = {
        "id": new_id(),
        "subcontract_id": sub["id"],
        "revision_number": 0,
        "lines": [],
        "status": "DRAFT",
        "approved_at": None,
    }
    _apply_allocation(rec, sub, lines)
    rec["status"] = "BALANCED"
    stamp(rec)
    DB["schedule_of_values"][rec["id"]] = rec
    sub["sov_status"] = "BALANCED"
    touch(sub)
    return ok(ser_sov(rec), status=201)


@bp.get("/subcontracts/<sub_id>/schedule-of-values")
def list_sovs(sub_id):
    auth(ALL_ROLES)
    sub = get_subcontract(sub_id)
    limit, offset = pagination_args()
    items = sorted_created(
        [s for s in DB["schedule_of_values"].values() if s["subcontract_id"] == sub["id"]]
    )
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_sov(s) for s in page], total, limit, offset)


@bp.get("/schedule-of-values/<sov_id>")
def get_one_sov(sov_id):
    auth(ALL_ROLES)
    return ok(ser_sov(get_sov(sov_id)))


@bp.post("/schedule-of-values/<sov_id>/reject")
def reject_sov(sov_id):
    auth(["OperationsManager"])
    sov = get_sov(sov_id)
    data = body()
    as_str(required(data, "reason"), "reason")
    if sov["status"] != "BALANCED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "ScheduleOfValues is not BALANCED"
        )
    sov["status"] = "REJECTED"
    touch(sov)
    sub = get_subcontract(sov["subcontract_id"])
    sub["sov_status"] = "REJECTED"
    touch(sub)
    return ok(ser_sov(sov))


@bp.post("/schedule-of-values/<sov_id>/revise")
def revise_sov(sov_id):
    auth(["BuyoutLead"])
    sov = get_sov(sov_id)
    data = body()
    lines = _validate_lines(required(data, "lines"))
    if sov["status"] != "REJECTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "ScheduleOfValues is not REJECTED"
        )
    sub = get_subcontract(sov["subcontract_id"])
    sov["revision_number"] += 1
    sov["status"] = "REVISED"
    _apply_allocation(sov, sub, lines)
    sov["status"] = "BALANCED"
    touch(sov)
    sub["sov_status"] = "BALANCED"
    touch(sub)
    return ok(ser_sov(sov))


@bp.post("/schedule-of-values/<sov_id>/approve")
def approve_sov(sov_id):
    auth(["OperationsManager"])
    sov = get_sov(sov_id)
    if sov["status"] != "BALANCED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "ScheduleOfValues is not BALANCED"
        )
    sub = get_subcontract(sov["subcontract_id"])
    project = get_project(package_of(sub)["project_id"])
    sov["status"] = "APPROVED"
    sov["approved_at"] = project["current_time_utc"]
    touch(sov)
    sub["sov_status"] = "APPROVED"
    touch(sub)
    return ok(ser_sov(sov))
