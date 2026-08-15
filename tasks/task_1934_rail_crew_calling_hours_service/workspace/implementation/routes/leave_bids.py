from datetime import timedelta

from flask import Blueprint, request

from db import store, base_record, touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_TEMPORAL_WINDOW,
    ERR_LEAVE_CONFLICT,
)
from middleware import auth, require_roles, require_owner
from response import ok_obj, paged
from services import (
    LEAVE_TYPES,
    LEAVE_QUOTA_PER_CRAFT_DAY,
    vacate_employee_slots,
    return_to_board_tail,
)
from validators import body, req_str, req_enum, req_dt

bp = Blueprint("leave_bids", __name__)

ALL_ROLES = ("CrewManager", "CrewCaller", "Employee")


def _get_bid(bid_id):
    bid = store.leave_bids.get(bid_id)
    if bid is None:
        raise ApiError(ERR_NOT_FOUND, 404, "LeaveBid '%s' not found." % bid_id)
    return bid


@bp.post("/api/leave-bids")
def create_bid():
    data = body()
    employee_id = req_str(data, "employee_id")
    leave_type = req_enum(data, "leave_type", LEAVE_TYPES)
    start_date = req_dt(data, "start_date")
    end_date = req_dt(data, "end_date")
    _, role = auth()
    require_roles(role, ("Employee",))
    if store.employees.get(employee_id) is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Employee '%s' not found." % employee_id)
    if start_date > end_date:
        raise ApiError(
            ERR_TEMPORAL_WINDOW, 422,
            "start_date must fall on or before end_date.",
        )
    if start_date.date() < store.now.date():
        raise ApiError(ERR_TEMPORAL_WINDOW, 422, "start_date must not be in the past.")
    rec = base_record()
    rec.update({
        "employee_id": employee_id,
        "leave_type": leave_type,
        "start_date": start_date,
        "end_date": end_date,
        "bid_status": "SUBMITTED",
        "decided_at": None,
    })
    store.leave_bids[rec["id"]] = rec
    return ok_obj(rec, 201)


@bp.get("/api/leave-bids")
def list_bids():
    _, role = auth()
    require_roles(role, ALL_ROLES)
    rows = list(store.leave_bids.values())
    employee_id = request.args.get("employee_id")
    if employee_id is not None:
        rows = [r for r in rows if r["employee_id"] == employee_id]
    bs = request.args.get("bid_status")
    if bs is not None:
        rows = [r for r in rows if r["bid_status"] == bs]
    return paged(rows, request.args)


@bp.get("/api/leave-bids/<bid_id>")
def get_bid(bid_id):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    return ok_obj(_get_bid(bid_id))


def _days_between(start_dt, end_dt):
    d = start_dt.date()
    last = end_dt.date()
    while d <= last:
        yield d
        d = d + timedelta(days=1)


@bp.post("/api/leave-bids/<bid_id>/award")
def award_bid(bid_id):
    _, role = auth()
    require_roles(role, ("CrewManager",))
    bid = _get_bid(bid_id)
    if bid["bid_status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "LeaveBid is not SUBMITTED.")
    bidder = store.employees.get(bid["employee_id"])
    if bidder is None or bidder["availability_status"] != "AVAILABLE":
        raise ApiError(ERR_INVALID_STATE, 409, "Employee is not AVAILABLE.")
    start, end = bid["start_date"], bid["end_date"]
    # Overlap gate: no other AWARDED bid for the same employee may overlap the
    # requested window; intervals are CLOSED — a shared boundary day conflicts.
    for other in store.leave_bids.values():
        if (
            other["id"] != bid["id"]
            and other["employee_id"] == bid["employee_id"]
            and other["bid_status"] == "AWARDED"
            and other["start_date"] <= end
            and other["end_date"] >= start
        ):
            raise ApiError(
                ERR_LEAVE_CONFLICT, 422,
                "An overlapping AWARDED bid exists for this employee.",
            )
    # Per-craft-per-day quota: for every day of the window, the count of other
    # AWARDED bids of the bidder's craft at the bidder's home_terminal covering
    # that day must be strictly below LEAVE_QUOTA_PER_CRAFT_DAY (i.e. zero).
    peers = [
        other for other in store.leave_bids.values()
        if other["id"] != bid["id"] and other["bid_status"] == "AWARDED"
        and store.employees.get(other["employee_id"]) is not None
        and store.employees[other["employee_id"]]["craft"] == bidder["craft"]
        and store.employees[other["employee_id"]]["home_terminal"] == bidder["home_terminal"]
    ]
    for day in _days_between(start, end):
        covering = sum(
            1 for other in peers
            if other["start_date"].date() <= day <= other["end_date"].date()
        )
        if covering >= LEAVE_QUOTA_PER_CRAFT_DAY:
            raise ApiError(
                ERR_LEAVE_CONFLICT, 422,
                "The per-craft-per-day leave quota would be exceeded.",
            )
    bid["bid_status"] = "AWARDED"
    bid["decided_at"] = store.now
    touch(bid)
    # Cascade: employee AVAILABLE -> ON_LEAVE; ACTIVE slots VACATED; renumber.
    bidder["availability_status"] = "ON_LEAVE"
    touch(bidder)
    vacate_employee_slots(bidder["id"])
    return ok_obj(bid)


@bp.post("/api/leave-bids/<bid_id>/deny")
def deny_bid(bid_id):
    _, role = auth()
    require_roles(role, ("CrewManager",))
    bid = _get_bid(bid_id)
    if bid["bid_status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "LeaveBid is not SUBMITTED.")
    bid["bid_status"] = "DENIED"
    bid["decided_at"] = store.now
    touch(bid)
    return ok_obj(bid)


@bp.post("/api/leave-bids/<bid_id>/cancel")
def cancel_bid(bid_id):
    uid, role = auth()
    require_roles(role, ("Employee",))
    bid = _get_bid(bid_id)
    require_owner(uid, bid["employee_id"])
    if bid["bid_status"] == "SUBMITTED":
        bid["bid_status"] = "CANCELLED"
        touch(bid)
        return ok_obj(bid)
    if bid["bid_status"] == "AWARDED":
        if not store.now < bid["start_date"]:
            raise ApiError(
                ERR_INVALID_STATE, 409,
                "The leave has begun; it can no longer be cancelled.",
            )
        bid["bid_status"] = "CANCELLED"
        touch(bid)
        emp = store.employees.get(bid["employee_id"])
        if emp is not None and emp["availability_status"] == "ON_LEAVE":
            emp["availability_status"] = "AVAILABLE"
            touch(emp)
            return_to_board_tail(emp)
        return ok_obj(bid)
    raise ApiError(ERR_INVALID_STATE, 409, "LeaveBid is not SUBMITTED or AWARDED.")
