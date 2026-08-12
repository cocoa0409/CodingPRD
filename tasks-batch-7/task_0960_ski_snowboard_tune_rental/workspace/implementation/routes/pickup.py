from flask import Blueprint, g, request

from auth import auth, check_own
from envelope import created, list_response, success
from errors import err
from services import refresh_window, window_end_dt
from store import db, is_date_str, is_time_str, new_entity, now, pub, touch
from validate import body, get_or_404, req_date, req_int, req_str, req_time

bp = Blueprint("pickup", __name__)

ALL_ROLES = ("Customer", "FrontDesk", "Technician", "Manager")


# ---------------------------------------------------------------------------
# Pickup windows
# ---------------------------------------------------------------------------

@bp.post("/shop/pickup-windows")
def create_pickup_window():
    auth("Manager")
    b = body()
    # half-open interval check (priority 7) before generic field checks (10)
    st, et = b.get("start_time"), b.get("end_time")
    if is_time_str(st) and is_time_str(et) and et <= st:
        raise err("ERR_DATE_RANGE_INVALID", "end_time must be after start_time")
    service_date = req_date(b, "service_date")
    start_time = req_time(b, "start_time")
    end_time = req_time(b, "end_time")
    location = req_str(b, "location_label")
    capacity = req_int(b, "van_capacity", minimum=1)
    # half-open [start, end): adjacency allowed, strict overlap rejected
    for w in db.pickup_windows.values():
        if (w["location_label"] == location
                and w["service_date"] == service_date
                and start_time < w["end_time"]
                and w["start_time"] < end_time):
            raise err("ERR_WINDOW_OVERLAP",
                      "Window strictly overlaps an existing window at this "
                      "location and date")
    window = new_entity({
        "service_date": service_date,
        "start_time": start_time,
        "end_time": end_time,
        "location_label": location,
        "van_capacity": capacity,
        "booked_count": 0,
        "posture": "OPEN",
    })
    db.pickup_windows[window["id"]] = window
    refresh_window(window)
    return created(pub(window))


@bp.get("/shop/pickup-windows/<wid>")
def get_pickup_window(wid):
    auth(*ALL_ROLES)
    window = get_or_404(db.pickup_windows, wid, "Pickup window")
    return success(pub(window))


@bp.get("/shop/pickup-windows")
def list_pickup_windows():
    auth(*ALL_ROLES)
    items = list(db.pickup_windows.values())
    service_date = request.args.get("service_date")
    location = request.args.get("location_label")
    posture = request.args.get("posture")
    if service_date is not None:
        items = [w for w in items if w["service_date"] == service_date]
    if location is not None:
        items = [w for w in items if w["location_label"] == location]
    if posture is not None:
        items = [w for w in items if w["posture"] == posture]
    return list_response(items)


# ---------------------------------------------------------------------------
# Pickup bookings
# ---------------------------------------------------------------------------

@bp.post("/shop/pickup-bookings")
def create_pickup_booking():
    auth("Customer", "FrontDesk", "Manager")
    b = body()
    window_id = b.get("pickup_window_id")
    res_id = b.get("reservation_id")
    if window_id is not None:
        get_or_404(db.pickup_windows, window_id, "Pickup window")
    if res_id is not None:
        get_or_404(db.reservations, res_id, "Reservation")
    window_id = req_str(b, "pickup_window_id")
    res_id = req_str(b, "reservation_id")
    res = db.reservations[res_id]
    check_own(res["customer_id"])
    window = db.pickup_windows[window_id]
    # three checks in PRD order: expired, full, reservation confirmed
    if now() >= window_end_dt(window):
        raise err("ERR_WINDOW_EXPIRED",
                  "The pickup window's end is in the past")
    if window["booked_count"] >= window["van_capacity"]:
        raise err("ERR_WINDOW_FULL", "The pickup window is FULL")
    if res["fulfillment_status"] != "CONFIRMED":
        raise err("ERR_RESERVATION_NOT_CONFIRMED",
                  "The reservation must be CONFIRMED to book slope-side pickup")
    booking = new_entity({
        "pickup_window_id": window_id,
        "reservation_id": res_id,
        "status": "BOOKED",
    })
    db.pickup_bookings[booking["id"]] = booking
    refresh_window(window)  # booked_count += 1; may tip OPEN -> FULL
    return created(pub(booking))


@bp.get("/shop/pickup-bookings/<bid>")
def get_pickup_booking(bid):
    auth(*ALL_ROLES)
    booking = get_or_404(db.pickup_bookings, bid, "Pickup booking")
    check_own(db.reservations[booking["reservation_id"]]["customer_id"])
    return success(pub(booking))


@bp.get("/shop/pickup-bookings")
def list_pickup_bookings():
    auth(*ALL_ROLES)
    items = list(db.pickup_bookings.values())
    if g.user_role == "Customer":
        items = [b for b in items
                 if db.reservations[b["reservation_id"]]["customer_id"] == g.user_id]
    window_id = request.args.get("pickup_window_id")
    res_id = request.args.get("reservation_id")
    status = request.args.get("status")
    if window_id is not None:
        items = [b for b in items if b["pickup_window_id"] == window_id]
    if res_id is not None:
        items = [b for b in items if b["reservation_id"] == res_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return list_response(items)


@bp.post("/shop/pickup-bookings/<bid>/cancel")
def cancel_pickup_booking(bid):
    auth("Customer", "FrontDesk", "Manager")
    booking = get_or_404(db.pickup_bookings, bid, "Pickup booking")
    check_own(db.reservations[booking["reservation_id"]]["customer_id"])
    if booking["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "Only a BOOKED booking can be cancelled")
    window = db.pickup_windows[booking["pickup_window_id"]]
    if window["posture"] == "CLOSED":
        raise err("ERR_INVALID_STATE",
                  "Cannot cancel a booking whose window is CLOSED")
    booking["status"] = "CANCELLED"
    touch(booking)
    refresh_window(window)  # booked_count -= 1; FULL -> OPEN possible
    return success(pub(booking))


@bp.post("/shop/pickup-bookings/<bid>/complete")
def complete_pickup_booking(bid):
    auth("FrontDesk", "Manager")
    booking = get_or_404(db.pickup_bookings, bid, "Pickup booking")
    if booking["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "Only a BOOKED booking can be completed")
    window = db.pickup_windows[booking["pickup_window_id"]]
    if window["posture"] == "CLOSED":
        raise err("ERR_INVALID_STATE",
                  "Cannot complete a booking whose window is CLOSED")
    booking["status"] = "COMPLETED"
    touch(booking)
    refresh_window(window)
    return success(pub(booking))
