"""Vendor assignment scheduling and the vendor-driven lifecycle (PRD §3.4)."""
from datetime import timedelta

from flask import Blueprint, g

import db
import services
from db import store
from errors import ApiError
from middleware import authenticate, require_roles
from response import created, ok, paged
from validation import get_body, validate_schema

bp = Blueprint("assignments", __name__)

READ_ROLES = ["RegionalManager", "PropertyManager", "TurnCoordinator",
              "Inspector", "Vendor"]

ASSIGNMENT_SCHEMA = {
    "scope_item_id": ("string", True, None),
    "vendor_id": ("string", True, None),
    "start_date": ("date", True, None),
    "end_date": ("date", True, None),
}

COMPLETE_SCHEMA = {
    "actual_cost_cents": ("integer", True, None),
}


def _get_assignment_or_404(assignment_id):
    asg = store.assignments.get(assignment_id)
    if asg is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Vendor assignment not found")
    return asg


def _check_vendor_ownership(asg):
    """Validation chain step 5 (PRD §2.1): only the assigned vendor may act."""
    if g.user_id != asg["vendor_id"]:
        raise ApiError("ERR_VENDOR_NOT_ASSIGNED", 403,
                       "X-User-ID must equal the assignment's vendor_id")


@bp.post("/make-ready/vendor-assignments")
def create_vendor_assignment():
    authenticate()
    require_roles(["TurnCoordinator"])
    body = get_body()
    validate_schema(body, ASSIGNMENT_SCHEMA)
    start = db.parse_date(body["start_date"])
    end = db.parse_date(body["end_date"])
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "end_date must fall after start_date")
    item = store.scope_items.get(body["scope_item_id"])
    if item is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Scope item not found")
    vendor = store.vendors.get(body["vendor_id"])
    if vendor is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Vendor not found")
    if item["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PLANNED scope item can be scheduled")
    # Business referential (PRD §2.8 step 8): trade discipline.
    if vendor["trade"] != services.TRADE_FOR_CATEGORY[item["category"]]:
        raise ApiError("ERR_VENDOR_TRADE_MISMATCH", 422,
                       "Vendor trade does not match the scope item's "
                       "category mapping")
    # Business temporal (step 9): vendor calendar, unit window, cure buffer.
    for a in store.assignments.values():
        if (a["vendor_id"] == vendor["id"]
                and a["status"] in services.OPEN_ASSIGNMENT_STATUSES):
            a_start = db.parse_date(a["start_date"])
            a_end = db.parse_date(a["end_date"])
            if start < a_end and a_start < end:
                raise ApiError("ERR_VENDOR_OVERLAP", 422,
                               "Window collides with another SCHEDULED or "
                               "ACCEPTED assignment of this vendor")
    turn_assignments = services.assignments_of_turn(item["turn_id"])
    for a in turn_assignments:
        if a["status"] in services.OPEN_ASSIGNMENT_STATUSES:
            a_start = db.parse_date(a["start_date"])
            a_end = db.parse_date(a["end_date"])
            if start < a_end and a_start < end:
                raise ApiError("ERR_UNIT_WINDOW_OVERLAP", 422,
                               "One crew in the unit at a time: the window "
                               "shares a calendar day with another active "
                               "assignment on this turn")
    if item["category"] == "CARPET":
        paint_ends = []
        for a in turn_assignments:
            if a["status"] in ("SCHEDULED", "ACCEPTED", "COMPLETED"):
                a_item = store.scope_items.get(a["scope_item_id"])
                if a_item is not None and a_item["category"] == "PAINT":
                    paint_ends.append(db.parse_date(a["end_date"]))
        if paint_ends:
            earliest = max(paint_ends) + timedelta(
                days=services.CURE_BUFFER_DAYS)
            if start < earliest:
                raise ApiError("ERR_CURE_BUFFER_VIOLATION", 422,
                               "CARPET work must start at least one cure day "
                               "after the latest paint assignment's end_date")
    # Business constraint (step 10): category sequencing.
    rank = item["sequence_rank"]
    for other in services.items_of_turn(item["turn_id"]):
        if (other["id"] != item["id"] and other["sequence_rank"] < rank
                and other["status"] in ("PLANNED", "PENDING_APPROVAL",
                                        "SCHEDULED")):
            raise ApiError("ERR_SEQUENCE_VIOLATION", 422,
                           "A same-turn item with a lower sequence rank is "
                           "still pending")
    asg = {
        "id": db.new_id(),
        "scope_item_id": item["id"],
        "vendor_id": vendor["id"],
        "start_date": body["start_date"],
        "end_date": body["end_date"],
        "status": "SCHEDULED",
        "actual_cost_cents": None,
    }
    db.new_common(asg)
    store.assignments[asg["id"]] = asg
    item["status"] = "SCHEDULED"
    db.touch(item)
    turn = store.turns[item["turn_id"]]
    services.sync_turn(turn)
    return created(asg)


@bp.get("/make-ready/vendor-assignments/<assignment_id>")
def get_vendor_assignment(assignment_id):
    authenticate()
    require_roles(READ_ROLES)
    return ok(_get_assignment_or_404(assignment_id))


@bp.get("/make-ready/vendor-assignments")
def list_vendor_assignments():
    authenticate()
    require_roles(READ_ROLES)
    page, pg = paged(list(store.assignments.values()),
                     ("vendor_id", "scope_item_id", "status"))
    return ok(page, rtype="array", pagination=pg)


@bp.post("/make-ready/vendor-assignments/<assignment_id>/accept")
def accept_assignment(assignment_id):
    authenticate()
    require_roles(["Vendor"])
    validate_schema(get_body(), {})
    asg = _get_assignment_or_404(assignment_id)
    _check_vendor_ownership(asg)
    if asg["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SCHEDULED assignment can be accepted")
    asg["status"] = "ACCEPTED"
    db.touch(asg)
    item = store.scope_items[asg["scope_item_id"]]
    turn = store.turns[item["turn_id"]]
    if turn["status"] == "SCOPED":
        turn["status"] = "IN_PROGRESS"
        db.touch(turn)  # version += 1 (PRD §3.4)
    elif turn["status"] == "REWORK" and item["rework_of_item_id"] is not None:
        turn["status"] = "IN_PROGRESS"
        db.touch(turn)  # version += 1 (PRD §3.4)
    services.sync_turn(turn)
    return ok(asg)


@bp.post("/make-ready/vendor-assignments/<assignment_id>/decline")
def decline_assignment(assignment_id):
    authenticate()
    require_roles(["Vendor"])
    validate_schema(get_body(), {})
    asg = _get_assignment_or_404(assignment_id)
    _check_vendor_ownership(asg)
    if asg["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SCHEDULED assignment can be declined")
    asg["status"] = "DECLINED"
    db.touch(asg)
    item = store.scope_items[asg["scope_item_id"]]
    item["status"] = "PLANNED"
    db.touch(item)
    turn = store.turns[item["turn_id"]]
    services.sync_turn(turn)
    return ok(asg)


@bp.post("/make-ready/vendor-assignments/<assignment_id>/complete")
def complete_assignment(assignment_id):
    authenticate()
    require_roles(["Vendor"])
    body = get_body()
    validate_schema(body, COMPLETE_SCHEMA)
    asg = _get_assignment_or_404(assignment_id)
    _check_vendor_ownership(asg)
    if asg["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ACCEPTED assignment can be completed")
    asg["status"] = "COMPLETED"
    asg["actual_cost_cents"] = body["actual_cost_cents"]
    db.touch(asg)
    item = store.scope_items[asg["scope_item_id"]]
    item["status"] = "COMPLETED"
    item["actual_cost_cents"] = body["actual_cost_cents"]
    db.touch(item)
    turn = store.turns[item["turn_id"]]
    services.sync_turn(turn)
    return ok(asg)
