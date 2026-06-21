"""Ride lifecycle (create/read/list), return-window create/read/list, and the
ride-posture cascades: declare-down, restore, close, redistribute (PRD §3.1, §3.7)."""
from flask import Blueprint

import db
import domain
import errors
import lookups
import response
import serialize
import validate_input as vi
from middleware import get_principal, require_roles

bp = Blueprint("rides", __name__)


# ---------------------------------------------------------------------------
# Ride create / read / list
# ---------------------------------------------------------------------------
@bp.post("/parks/<pid>/rides")
def create_ride(pid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin"})
    park = lookups.get_park(pid)
    body = vi.get_body()

    name = vi.require_str(body, "name")
    hourly = vi.require_int(body, "hourly_throughput", min_val=1)
    min_height = vi.opt_int(body, "min_height_cm", default=0, min_val=0)
    wheelchair = vi.opt_bool(body, "wheelchair_transfer_required", default=False)
    single_rider = vi.opt_bool(body, "single_rider_enabled", default=False)

    ride = db.stamp_new({
        "park_id": park["id"],
        "name": name,
        "hourly_throughput": hourly,
        "min_height_cm": min_height,
        "wheelchair_transfer_required": wheelchair,
        "single_rider_enabled": single_rider,
        "operational_status": "OPEN",
        "booked_slot_count": 0,
        "posted_wait_minutes": 0,
    })
    domain.recompute_posted_wait(ride)
    db.rides[ride["id"]] = ride
    return response.object_response(serialize.view("ride", ride), 201)


@bp.get("/parks/<pid>/rides")
def list_park_rides(pid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "RideOperator", "GuestApp"})
    park = lookups.get_park(pid)
    records = [r for r in db.rides.values() if r["park_id"] == park["id"]]
    return lookups.paginate_and_respond("ride", records, response)


@bp.get("/rides/<rid>")
def read_ride(rid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "RideOperator", "GuestApp"})
    ride = lookups.get_ride(rid)
    return response.object_response(serialize.view("ride", ride), 200)


# ---------------------------------------------------------------------------
# ReturnWindow create / read / list
# ---------------------------------------------------------------------------
@bp.post("/rides/<rid>/return-windows")
def create_window(rid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin"})
    ride = lookups.get_ride(rid)
    body = vi.get_body()

    start_raw = vi.require_str(body, "window_start_utc")
    end_raw = vi.require_str(body, "window_end_utc")
    start_dt = domain.parse_dt(start_raw, "window_start_utc")
    end_dt = domain.parse_dt(end_raw, "window_end_utc")

    slot_capacity = domain.compute_slot_capacity(ride["hourly_throughput"], start_dt, end_dt)

    window = db.stamp_new({
        "ride_id": ride["id"],
        "window_start_utc": start_raw,
        "window_end_utc": end_raw,
        "slot_capacity": slot_capacity,
        "reserved_count": 0,
        "window_status": "OPEN",
    })
    db.return_windows[window["id"]] = window
    return response.object_response(serialize.view("return_window", window), 201)


@bp.get("/rides/<rid>/return-windows")
def list_ride_windows(rid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "RideOperator", "GuestApp"})
    ride = lookups.get_ride(rid)
    records = [w for w in db.return_windows.values() if w["ride_id"] == ride["id"]]
    return lookups.paginate_and_respond("return_window", records, response)


@bp.get("/return-windows/<wid>")
def read_window(wid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "RideOperator", "GuestApp"})
    window = lookups.get_window(wid)
    return response.object_response(serialize.view("return_window", window), 200)


# ---------------------------------------------------------------------------
# Ride posture cascades
# ---------------------------------------------------------------------------
def _park_of_ride(ride):
    return db.parks.get(ride["park_id"])


@bp.post("/rides/<rid>/declare-down")
def declare_down(rid):
    _, role = get_principal()
    require_roles(role, {"RideOperator"})
    ride = lookups.get_ride(rid)

    if ride["operational_status"] != "OPEN":
        errors.err(errors.ERR_INVALID_STATE, "Ride is not OPEN")

    ride["operational_status"] = "DOWN"

    # child windows OPEN/EXHAUSTED -> SUSPENDED
    for w in db.return_windows.values():
        if w["ride_id"] == ride["id"] and w["window_status"] in ("OPEN", "EXHAUSTED"):
            w["window_status"] = "SUSPENDED"
            db.touch(w)

    # BOOKED reservations -> REDISTRIBUTED; debit old window + ride counters
    for r in db.reservations.values():
        if r["ride_id"] != ride["id"] or r["reservation_status"] != "BOOKED":
            continue
        r["reservation_status"] = "REDISTRIBUTED"
        r["redistributed_from_window_id"] = r["return_window_id"]
        db.touch(r)
        if r["queue_type"] == "VIRTUAL_QUEUE":
            window = db.return_windows.get(r["return_window_id"])
            if window is not None:
                window["reserved_count"] -= 1
                db.touch(window)
            ride["booked_slot_count"] -= 1

    # ACTIVE LightningLanePurchases on this ride -> REFUNDED (credit charged_cents)
    for p in db.lightning_lane_purchases.values():
        if p["ride_id"] == ride["id"] and p["hold_status"] == "ACTIVE":
            p["hold_status"] = "REFUNDED"
            db.touch(p)

    domain.recompute_ride_booked_slot_count(ride)
    domain.recompute_posted_wait(ride)
    db.touch(ride)
    return response.object_response(serialize.view("ride", ride), 200)


@bp.post("/rides/<rid>/restore")
def restore(rid):
    _, role = get_principal()
    require_roles(role, {"RideOperator"})
    ride = lookups.get_ride(rid)

    if ride["operational_status"] != "DOWN":
        errors.err(errors.ERR_INVALID_STATE, "Ride is not DOWN")

    ride["operational_status"] = "OPEN"
    park = _park_of_ride(ride)
    now = domain.park_now(park)

    for w in db.return_windows.values():
        if w["ride_id"] != ride["id"] or w["window_status"] != "SUSPENDED":
            continue
        end = domain.parse_dt(w["window_end_utc"], "window_end_utc")
        if now is not None and now >= end:
            w["window_status"] = "EXPIRED"
        else:
            w["window_status"] = "OPEN"
        db.touch(w)

    domain.recompute_posted_wait(ride)
    db.touch(ride)
    return response.object_response(serialize.view("ride", ride), 200)


@bp.post("/rides/<rid>/close")
def close_ride(rid):
    _, role = get_principal()
    require_roles(role, {"RideOperator"})
    ride = lookups.get_ride(rid)

    if ride["operational_status"] != "OPEN":
        errors.err(errors.ERR_INVALID_STATE, "Ride is not OPEN")

    ride["operational_status"] = "CLOSED"

    for w in db.return_windows.values():
        if w["ride_id"] == ride["id"] and w["window_status"] != "EXPIRED":
            w["window_status"] = "EXPIRED"
            db.touch(w)

    for r in db.reservations.values():
        if r["ride_id"] == ride["id"] and r["reservation_status"] in ("HELD", "BOOKED"):
            r["reservation_status"] = "FORFEITED"
            db.touch(r)

    domain.recompute_ride_booked_slot_count(ride)
    domain.recompute_posted_wait(ride)
    db.touch(ride)
    return response.object_response(serialize.view("ride", ride), 200)


@bp.post("/rides/<rid>/redistribute")
def redistribute(rid):
    _, role = get_principal()
    require_roles(role, {"RideOperator"})
    ride = lookups.get_ride(rid)
    park = _park_of_ride(ride)
    now = domain.park_now(park)

    rehomed_reservation_ids = []
    unplaced_reservation_ids = []

    # Process REDISTRIBUTED reservations in creation order for determinism.
    stranded = sorted(
        (r for r in db.reservations.values()
         if r["ride_id"] == ride["id"] and r["reservation_status"] == "REDISTRIBUTED"),
        key=lambda r: r["_seq"],
    )

    for res in stranded:
        replacement = _select_replacement_window(ride, now)
        if replacement is None:
            unplaced_reservation_ids.append(res["id"])
            continue
        res["return_window_id"] = replacement["id"]
        res["reservation_status"] = "BOOKED"
        db.touch(res)
        replacement["reserved_count"] += 1
        db.touch(replacement)
        domain.maybe_exhaust_window(replacement)
        ride["booked_slot_count"] += 1
        rehomed_reservation_ids.append(res["id"])

    domain.recompute_posted_wait(ride)
    db.touch(ride)

    if unplaced_reservation_ids:
        # Surface the error per PRD §3.7, but the placements that succeeded stand.
        # Tests treat ERR_NO_REPLACEMENT_WINDOW as the outcome when any reservation
        # remains unplaced.
        errors.err(errors.ERR_NO_REPLACEMENT_WINDOW,
                   "No replacement window available for one or more reservations")

    return response.object_response({
        "rehomed_count": len(rehomed_reservation_ids),
        "rehomed_reservation_ids": rehomed_reservation_ids,
        "unplaced_reservation_ids": unplaced_reservation_ids,
    }, 200)


def _select_replacement_window(ride, now):
    """Earliest window_start_utc, tie-break earliest created_at; OPEN, has room,
    window_end_utc still after current_utc (PRD §3.7)."""
    candidates = []
    for w in db.return_windows.values():
        if w["ride_id"] != ride["id"]:
            continue
        if w["window_status"] != "OPEN":
            continue
        if w["reserved_count"] >= w["slot_capacity"]:
            continue
        end = domain.parse_dt(w["window_end_utc"], "window_end_utc")
        if now is not None and now >= end:
            continue
        start = domain.parse_dt(w["window_start_utc"], "window_start_utc")
        candidates.append((start, w["created_at"], w["_seq"], w))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1], t[2]))
    return candidates[0][3]
