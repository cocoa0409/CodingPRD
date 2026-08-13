"""TourStop endpoints (PRD §3.2, §3.6, §3.9)."""

from datetime import timedelta
from flask import Blueprint, request
import errors
from db import store
from middleware import get_auth, require_roles
from response import success_object, success_list
from services import domain
from util import (body, req_str, opt_int, parse_date, parse_datetime, new_resource,
                  touch, pagination_params, paginate, sort_by_created)

bp = Blueprint("stops", __name__)

READ_ROLES = {"OpsManager", "TourManager", "LogisticsCoordinator", "WarehouseTech"}


def _validate_stop_window(tour, venue_dt, load_in_dt):
    """Gate 9: venue_date within [tour.start_date, tour.end_date];
    load_in_ts strictly before 20:00 on the venue date (PRD §3.2)."""
    tour_start = parse_date(tour["start_date"], "start_date")
    tour_end = parse_date(tour["end_date"], "end_date")
    if venue_dt < tour_start or venue_dt > tour_end:
        raise errors.invalid_window("venue_date must lie within the tour window")
    cutoff = venue_dt.replace(hour=20, minute=0, second=0, microsecond=0)
    if load_in_dt >= cutoff:
        raise errors.invalid_window("load_in_ts must precede 20:00 on the venue date")


@bp.route("/backline/tours/<tour_id>/stops", methods=["POST"])
def create_stop(tour_id):
    auth = get_auth()
    require_roles(auth, {"TourManager"})
    tour = domain.get_tour(tour_id)
    data = body()
    city_code = req_str(data, "city_code")
    if data.get("venue_date") is None:
        raise errors.invalid_request("Missing required field: venue_date")
    if data.get("load_in_ts") is None:
        raise errors.invalid_request("Missing required field: load_in_ts")
    venue_dt = parse_date(data.get("venue_date"), "venue_date")
    load_in_dt = parse_datetime(data.get("load_in_ts"), "load_in_ts")
    _validate_stop_window(tour, venue_dt, load_in_dt)
    stop = new_resource()
    stop.update({
        "tour_id": tour["id"],
        "city_code": city_code,
        "venue_date": data.get("venue_date"),
        "load_in_ts": data.get("load_in_ts"),
        "status": "PLANNED",
        "rider_revision": 0,
    })
    store.tour_stops[stop["id"]] = stop
    # Stop list feeds the activation gate: bump parent tour version + stop_count (§3.2)
    tour["stop_count"] = sum(1 for s in store.tour_stops.values() if s.get("tour_id") == tour["id"])
    touch(tour)
    return success_object(domain.serialize(stop), status=201)


@bp.route("/backline/tours/<tour_id>/stops", methods=["GET"])
def list_stops(tour_id):
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    domain.get_tour(tour_id)
    limit, offset = pagination_params()
    items = [s for s in store.tour_stops.values() if s.get("tour_id") == tour_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success_list([domain.serialize(s) for s in page], meta, status=200)


@bp.route("/backline/tour-stops/<stop_id>", methods=["GET"])
def fetch_stop(stop_id):
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    stop = domain.get_stop(stop_id)
    return success_object(domain.serialize(stop), status=200)


@bp.route("/backline/tour-stops/<stop_id>/stage", methods=["POST"])
def stage_stop(stop_id):
    auth = get_auth()
    require_roles(auth, {"LogisticsCoordinator"})
    stop = domain.get_stop(stop_id)
    if stop["status"] != "PLANNED":
        raise errors.invalid_state("Stop must be PLANNED to stage")
    tour = domain.get_tour(stop["tour_id"])
    if tour["status"] != "ACTIVE":
        raise errors.invalid_state("Parent tour must be ACTIVE to stage a stop")
    # Every rider line resolved: nothing left in REQUESTED or SUBSTITUTION_PENDING
    for rl in store.rider_lines.values():
        if rl.get("tour_stop_id") == stop["id"] and rl.get("status") not in \
                {"SOURCED", "APPROVED", "FULFILLED", "CANCELLED"}:
            raise errors.invalid_state("All rider lines must be resolved before staging")
    # At least one DELIVERED shipment bound for this stop's city
    has_delivered = any(
        s.get("tour_id") == tour["id"] and s.get("to_city_code") == stop["city_code"]
        and s.get("status") == "DELIVERED"
        for s in store.shipments.values())
    if not has_delivered:
        raise errors.invalid_state("No DELIVERED shipment covers this stop's city")
    stop["status"] = "GEAR_STAGED"
    touch(stop)
    return success_object(domain.serialize(stop), status=200)


@bp.route("/backline/tour-stops/<stop_id>/show-ready", methods=["POST"])
def show_ready_stop(stop_id):
    auth = get_auth()
    require_roles(auth, {"WarehouseTech"})
    stop = domain.get_stop(stop_id)
    if stop["status"] != "GEAR_STAGED":
        raise errors.invalid_state("Stop must be GEAR_STAGED to declare show-ready")
    for rl in store.rider_lines.values():
        if rl.get("tour_stop_id") == stop["id"] and rl.get("status") not in \
                {"FULFILLED", "CANCELLED"}:
            raise errors.invalid_state("All rider lines must be FULFILLED or CANCELLED")
    stop["status"] = "SHOW_READY"
    touch(stop)
    return success_object(domain.serialize(stop), status=200)


@bp.route("/backline/tour-stops/<stop_id>/load-out", methods=["POST"])
def load_out_stop(stop_id):
    auth = get_auth()
    require_roles(auth, {"WarehouseTech"})
    stop = domain.get_stop(stop_id)
    if stop["status"] != "SHOW_READY":
        raise errors.invalid_state("Stop must be SHOW_READY to load out")
    # Sweep every DELIVERED reservation feeding this stop into RETURNED,
    # running the check-in cascade on each affected unit (§3.6)
    feeding_res_ids = set()
    for rl in store.rider_lines.values():
        if rl.get("tour_stop_id") == stop["id"] and rl.get("fulfilled_by_reservation_id"):
            feeding_res_ids.add(rl["fulfilled_by_reservation_id"])
    for res_id in feeding_res_ids:
        r = store.reservation_lines.get(res_id)
        if r is not None and r.get("status") == "DELIVERED":
            domain.check_in_reservation(r, store.current_utc)
    stop["status"] = "LOADED_OUT"
    touch(stop)
    return success_object(domain.serialize(stop), status=200)


@bp.route("/backline/tour-stops/<stop_id>/settle", methods=["POST"])
def settle_stop(stop_id):
    auth = get_auth()
    require_roles(auth, {"TourManager"})
    stop = domain.get_stop(stop_id)
    if stop["status"] != "LOADED_OUT":
        raise errors.invalid_state("Stop must be LOADED_OUT to settle")
    # Every reservation feeding this stop must be SETTLED or CANCELLED
    for rl in store.rider_lines.values():
        if rl.get("tour_stop_id") == stop["id"] and rl.get("fulfilled_by_reservation_id"):
            r = store.reservation_lines.get(rl["fulfilled_by_reservation_id"])
            if r is not None and r.get("status") not in {"SETTLED", "CANCELLED"}:
                raise errors.invalid_state("All feeding reservations must be SETTLED or CANCELLED")
    stop["status"] = "SETTLED"
    touch(stop)
    return success_object(domain.serialize(stop), status=200)


@bp.route("/backline/tour-stops/<stop_id>/cancel", methods=["POST"])
def cancel_stop(stop_id):
    auth = get_auth()
    require_roles(auth, {"TourManager"})
    stop = domain.get_stop(stop_id)
    if stop["status"] != "PLANNED":
        raise errors.invalid_state("Only a PLANNED stop may be cancelled")
    # Cascade: rider lines in {REQUESTED, SOURCED, SUBSTITUTION_PENDING, APPROVED}
    for rl in store.rider_lines.values():
        if rl.get("tour_stop_id") == stop["id"] and rl.get("status") in \
                {"REQUESTED", "SOURCED", "SUBSTITUTION_PENDING", "APPROVED"}:
            rl["status"] = "CANCELLED"
            touch(rl)
    # Cascade: reservations sourced for this stop in {DRAFT, SOURCED}
    stop_line_ids = {rl["id"] for rl in store.rider_lines.values()
                     if rl.get("tour_stop_id") == stop["id"]}
    for r in store.reservation_lines.values():
        if r.get("rider_line_id") in stop_line_ids and r.get("status") in {"DRAFT", "SOURCED"}:
            domain.release_reservation(r)
            r["status"] = "CANCELLED"
            touch(r)
    stop["status"] = "CANCELLED"
    touch(stop)
    return success_object(domain.serialize(stop), status=200)
