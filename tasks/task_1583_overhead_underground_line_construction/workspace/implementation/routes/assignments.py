"""Assignment endpoints and daily production reporting (PRD 3.2, 3.3).

Validation ladder (PRD 2.9): auth -> role -> shape -> existence -> OCC ->
contract activity -> lifecycle gates -> work-safety gates -> business
constraints (schedule conflicts, quantity cap) -> cross-contract integrity.
"""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_OUTAGE_REQUIRED,
    ERR_EQUIPMENT_DOWN, ERR_CREW_SCHEDULE_CONFLICT,
    ERR_EQUIPMENT_SCHEDULE_CONFLICT, ERR_CREW_ON_STORM_DUTY,
    ERR_QUANTITY_CAP_EXCEEDED, ERR_INVALID_DATE_RANGE,
    ERR_CROSS_CONTRACT_REFERENCE,
)
from middleware import authorized
from response import success_object
from routes.helpers import serialize, list_response, get_one
from routes.work_packages import require_contract_active
from services.core import (
    new_record, touch, work_package_of_assignment, contract_of_work_package,
    outage_covers_date,
)
from util import dec, parse_date, CLOCK
from validate import (
    get_body, req_str, req_num, req_date, req_int, require_path_resource,
    require_body_ref,
)

bp = Blueprint("assignments", __name__)


def _intervals_overlap(a_start, a_end, b_start, b_end) -> bool:
    """Closed-interval overlap; pure adjacency (next start > prior end) allowed."""
    return a_start <= b_end and b_start <= a_end


@bp.post("/work-packages/<work_package_id>/assignments")
def create_assignment(work_package_id):
    authorized(["FOREMAN"])
    body = get_body()
    crew_id = req_str(body, "crew_id")
    equipment_id = req_str(body, "equipment_id")
    start_date = req_date(body, "start_date")
    end_date = req_date(body, "end_date")
    wp = require_path_resource("work_packages", work_package_id)
    crew = require_body_ref("crews", crew_id, "crew_id")
    equipment = require_body_ref("equipment", equipment_id, "equipment_id")
    contract = contract_of_work_package(wp)
    require_contract_active(contract)
    # Lifecycle gate (6c): work package must be MOBILIZED or IN_PROGRESS.
    if wp["status"] not in ("MOBILIZED", "IN_PROGRESS"):
        raise_error(ERR_INVALID_STATE,
                    "assignments require the work package to be MOBILIZED or IN_PROGRESS")
    # Work-safety gate (8b): equipment down for maintenance.
    if equipment["maintenance_flag"]:
        raise_error(ERR_EQUIPMENT_DOWN,
                    "equipment maintenance_flag is true; cannot be assigned")
    # Business constraints (9): crew / equipment schedule conflicts.
    ns, ne = parse_date(start_date), parse_date(end_date)
    for a in db["assignments"].values():
        if a["status"] not in ("PLANNED", "ACTIVE"):
            continue
        as_, ae = parse_date(a["start_date"]), parse_date(a["end_date"])
        if a["crew_id"] == crew_id and _intervals_overlap(ns, ne, as_, ae):
            raise_error(ERR_CREW_SCHEDULE_CONFLICT,
                        "crew already has an overlapping PLANNED/ACTIVE assignment")
    for a in db["assignments"].values():
        if a["status"] not in ("PLANNED", "ACTIVE"):
            continue
        as_, ae = parse_date(a["start_date"]), parse_date(a["end_date"])
        if a["equipment_id"] == equipment_id and _intervals_overlap(ns, ne, as_, ae):
            raise_error(ERR_EQUIPMENT_SCHEDULE_CONFLICT,
                        "equipment already has an overlapping PLANNED/ACTIVE assignment")
    # Storm-duty exclusivity (9e).
    for sa in db["storm_activations"].values():
        if sa["crew_id"] == crew_id and sa["status"] == "ACTIVE":
            raise_error(ERR_CREW_ON_STORM_DUTY,
                        "crew has an ACTIVE storm activation")
    # Date-range well-formedness (9h).
    if ne < ns:
        raise_error(ERR_INVALID_DATE_RANGE, "end_date must be >= start_date")

    rec = new_record("assignments", {
        "work_package_id": wp["id"],
        "crew_id": crew_id,
        "equipment_id": equipment_id,
        "start_date": start_date,
        "end_date": end_date,
        "status": "PLANNED",
    })
    touch(wp)  # assignment creation increments the work package's version
    return success_object(serialize("assignments", rec), status=201)


@bp.get("/assignments")
def list_assignments():
    filters = {
        "work_package_id": request.args.get("work_package_id"),
        "crew_id": request.args.get("crew_id"),
        "equipment_id": request.args.get("equipment_id"),
        "status": request.args.get("status"),
    }
    return list_response("assignments", filters)


@bp.get("/assignments/<assignment_id>")
def get_assignment(assignment_id):
    return get_one("assignments", assignment_id)


@bp.post("/assignments/<assignment_id>/transition")
def transition_assignment(assignment_id):
    authorized(["FOREMAN"])
    body = get_body()
    to = req_enum_transition(body)
    assignment = require_path_resource("assignments", assignment_id)
    wp = work_package_of_assignment(assignment)
    contract = contract_of_work_package(wp)
    require_contract_active(contract)
    cur = assignment["status"]

    if cur == "PLANNED" and to == "ACTIVE":
        today = CLOCK.today()
        if not (parse_date(assignment["start_date"]) <= today
                <= parse_date(assignment["end_date"])):
            raise_error(ERR_INVALID_STATE,
                        "activation requires today inside [start_date, end_date]")
        if wp["status"] not in ("MOBILIZED", "IN_PROGRESS"):
            raise_error(ERR_INVALID_STATE,
                        "activation requires work package MOBILIZED or IN_PROGRESS")
    elif cur == "ACTIVE" and to == "COMPLETED":
        for e in db["production_entries"].values():
            if (e["assignment_id"] == assignment["id"]
                    and e["status"] in ("SUBMITTED", "REWORK_REQUIRED")):
                raise_error(ERR_INVALID_STATE,
                            "completion blocked by SUBMITTED or REWORK_REQUIRED entries")
    elif to == "CANCELLED" and cur in ("PLANNED", "ACTIVE"):
        pass
    else:
        raise_error(ERR_INVALID_STATE,
                    f"cannot transition assignment from {cur} to {to}")

    assignment["status"] = to
    touch(assignment)
    return success_object(serialize("assignments", assignment))


def req_enum_transition(body):
    from validate import req_enum
    return req_enum(body, "to", {"ACTIVE", "COMPLETED", "CANCELLED"})


# ---------------------------------------------------------------------------
# Production entries (PRD 3.3)
# ---------------------------------------------------------------------------

def _quantity_cap_check(bid_item, contract, new_quantity, exclude_entry_id=None):
    """Cumulative reported units (SUBMITTED + ACCEPTED) plus the new quantity
    must be <= estimated_quantity x quantity_cap_pct; equality allowed."""
    cumulative = dec(0)
    for e in db["production_entries"].values():
        if e["bid_item_id"] != bid_item["id"]:
            continue
        if exclude_entry_id is not None and e["id"] == exclude_entry_id:
            continue
        if e["status"] in ("SUBMITTED", "ACCEPTED"):
            cumulative += dec(e["quantity_reported"])
    cap = dec(bid_item["estimated_quantity"]) * dec(contract["quantity_cap_pct"])
    if cumulative + dec(new_quantity) > cap:
        raise_error(ERR_QUANTITY_CAP_EXCEEDED,
                    "cumulative reported units would exceed the quantity cap")


@bp.post("/assignments/<assignment_id>/production-entries")
def create_production_entry(assignment_id):
    authorized(["FOREMAN"])
    body = get_body()
    bid_item_id = req_str(body, "bid_item_id")
    work_date = req_date(body, "work_date")
    quantity_reported = req_num(body, "quantity_reported", positive=True)
    expected_assignment_version = req_int(body, "expected_assignment_version")
    assignment = require_path_resource("assignments", assignment_id)
    bid_item = require_body_ref("bid_items", bid_item_id, "bid_item_id")
    # OCC (priority 5) precedes state evaluation.
    if expected_assignment_version != assignment["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_assignment_version does not match the assignment's current version")
    wp = work_package_of_assignment(assignment)
    contract = contract_of_work_package(wp)
    require_contract_active(contract)
    # Lifecycle gates (6c).
    if wp["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE,
                    "production reporting requires work package IN_PROGRESS")
    if assignment["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE,
                    "production reporting requires an ACTIVE assignment")
    wd = parse_date(work_date)
    if not (parse_date(assignment["start_date"]) <= wd
            <= parse_date(assignment["end_date"])):
        raise_error(ERR_INVALID_STATE,
                    "work_date must fall inside the assignment's working interval")
    # Outage gate (8): outage-dependent packages need IN_EFFECT coverage.
    if wp["requires_outage"] and not outage_covers_date(wp["id"], work_date):
        raise_error(ERR_OUTAGE_REQUIRED,
                    "no IN_EFFECT outage of this work package covers the work_date")
    # Quantity ceiling (9g), then cross-contract integrity (10).
    bid_contract = db["contracts"].get(bid_item["contract_id"])
    _quantity_cap_check(bid_item, bid_contract, quantity_reported)
    if bid_item["contract_id"] != contract["id"]:
        raise_error(ERR_CROSS_CONTRACT_REFERENCE,
                    "bid item belongs to a different contract than the work package")

    rec = new_record("production_entries", {
        "assignment_id": assignment["id"],
        "bid_item_id": bid_item_id,
        "work_date": work_date,
        "quantity_reported": quantity_reported,
        "rework_count": 0,
        "status": "SUBMITTED",
    })
    touch(assignment)  # posting production increments the assignment's version
    return success_object(serialize("production_entries", rec), status=201)


@bp.get("/production-entries")
def list_production_entries():
    filters = {
        "assignment_id": request.args.get("assignment_id"),
        "bid_item_id": request.args.get("bid_item_id"),
        "status": request.args.get("status"),
    }
    return list_response("production_entries", filters)


@bp.get("/production-entries/<production_entry_id>")
def get_production_entry(production_entry_id):
    return get_one("production_entries", production_entry_id)


@bp.post("/production-entries/<production_entry_id>/resubmit")
def resubmit_production_entry(production_entry_id):
    authorized(["FOREMAN"])
    get_body()
    entry = require_path_resource("production_entries", production_entry_id)
    assignment = require_path_resource("assignments", entry["assignment_id"])
    wp = work_package_of_assignment(assignment)
    contract = contract_of_work_package(wp)
    require_contract_active(contract)
    if entry["status"] != "REWORK_REQUIRED":
        raise_error(ERR_INVALID_STATE,
                    "only a REWORK_REQUIRED entry can be resubmitted")
    # Quantity cap re-applies (entry is REWORK_REQUIRED, so excluded from the
    # cumulative sum; its own quantity is added back).
    bid_item = require_path_resource("bid_items", entry["bid_item_id"])
    _quantity_cap_check(bid_item, contract, entry["quantity_reported"],
                        exclude_entry_id=entry["id"])
    entry["status"] = "SUBMITTED"
    entry["rework_count"] = entry.get("rework_count", 0) + 1
    touch(entry)
    return success_object(serialize("production_entries", entry))


@bp.post("/production-entries/<production_entry_id>/void")
def void_production_entry(production_entry_id):
    authorized(["FOREMAN"])
    get_body()
    entry = require_path_resource("production_entries", production_entry_id)
    assignment = require_path_resource("assignments", entry["assignment_id"])
    wp = work_package_of_assignment(assignment)
    contract = contract_of_work_package(wp)
    require_contract_active(contract)
    if entry["status"] not in ("SUBMITTED", "REWORK_REQUIRED"):
        raise_error(ERR_INVALID_STATE,
                    "only a SUBMITTED or REWORK_REQUIRED entry can be voided")
    entry["status"] = "VOID"
    touch(entry)
    return success_object(serialize("production_entries", entry))
