"""GroupBooking endpoints: hold (capacity-checked), confirm, release, cancel."""

from flask import Blueprint, request

import store
from store import touch, parse_dt
from common import get_or_404, single, list_result, filter_by, as_str, exists_or_404
from auth import authenticate
from validate import get_body, req_str, req_int, req_dt
from errors import ApiError, bad_request, invalid_state, ERR_VENDOR_CAPACITY_EXCEEDED

bp = Blueprint("groups", __name__)

READERS = {"TravelManager", "Traveler", "Approver", "FinanceOfficer"}


def _overlap(a_start, a_end, b_start, b_end):
    # closed intervals overlap
    return a_start <= b_end and b_start <= a_end


@bp.post("/tmc/group-bookings")
def create_group():
    authenticate({"TravelManager"})
    body = get_body()
    exists_or_404(store.vendors, body.get("vendor_id"))
    exists_or_404(store.travelers, body.get("organizer_traveler_id"))

    rec = {
        "vendor_id": req_str(body, "vendor_id"),
        "organizer_traveler_id": req_str(body, "organizer_traveler_id"),
        "block_size": req_int(body, "block_size", min_value=1),
        "confirmed_count": 0,
        "start_date": req_dt(body, "start_date"),
        "end_date": req_dt(body, "end_date"),
        "status": "HELD",
    }
    vendor = store.vendors[rec["vendor_id"]]

    new_start = parse_dt(rec["start_date"])
    new_end = parse_dt(rec["end_date"])
    occupied = 0
    for g in store.group_bookings.values():
        if g["vendor_id"] != rec["vendor_id"] or g["status"] not in ("HELD", "CONFIRMED"):
            continue
        if _overlap(new_start, new_end, parse_dt(g["start_date"]), parse_dt(g["end_date"])):
            occupied += g["block_size"]
    if occupied + rec["block_size"] > vendor["capacity"]:
        raise ApiError(ERR_VENDOR_CAPACITY_EXCEEDED, 409, "Vendor block capacity exceeded")

    store.stamp_new(rec)
    store.group_bookings[rec["id"]] = rec
    return single(rec, 201)


@bp.get("/tmc/group-bookings/<gid>")
def get_group(gid):
    authenticate(READERS)
    return single(get_or_404(store.group_bookings, gid))


@bp.get("/tmc/group-bookings")
def list_groups():
    authenticate(READERS)
    recs = filter_by(store.group_bookings.values(), request.args,
                     {"vendor_id": as_str, "organizer_traveler_id": as_str, "status": as_str})
    return list_result(recs)


@bp.post("/tmc/group-bookings/<gid>/confirm")
def confirm_group(gid):
    authenticate({"TravelManager"})
    group = get_or_404(store.group_bookings, gid)
    body = get_body()
    confirmed_count = req_int(body, "confirmed_count", min_value=0)
    if confirmed_count > group["block_size"]:
        raise bad_request("confirmed_count exceeds block_size")
    if group["status"] != "HELD":
        raise invalid_state("Group block is not HELD")
    group["confirmed_count"] = confirmed_count
    group["status"] = "CONFIRMED"
    touch(group)
    return single(group)


@bp.post("/tmc/group-bookings/<gid>/release")
def release_group(gid):
    authenticate({"TravelManager"})
    group = get_or_404(store.group_bookings, gid)
    if group["status"] != "CONFIRMED":
        raise invalid_state("Group block is not CONFIRMED")
    group["status"] = "RELEASED"
    touch(group)
    return single(group)


@bp.post("/tmc/group-bookings/<gid>/cancel")
def cancel_group(gid):
    authenticate({"TravelManager"})
    group = get_or_404(store.group_bookings, gid)
    if group["status"] != "HELD":
        raise invalid_state("Group block is not HELD")
    group["status"] = "CANCELLED"
    touch(group)
    return single(group)
