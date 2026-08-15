"""ReservationLine endpoints (PRD §3.6, §3.7, §3.9)."""

from flask import Blueprint, request
import errors
from db import store
from middleware import get_auth, require_roles
from response import success_object, success_list
from services import domain, calculations as calc
from util import (body, opt_int, opt_bool, opt_enum, parse_datetime, new_resource,
                  touch, pagination_params, paginate, sort_by_created, iso_z, day_count)

bp = Blueprint("reservations", __name__)

READ_ROLES = {"OpsManager", "TourManager", "LogisticsCoordinator", "WarehouseTech"}
SEVERITIES = {"COSMETIC", "MINOR", "MAJOR", "TOTAL_LOSS"}


@bp.route("/backline/reservation-lines/<res_id>", methods=["GET"])
def fetch_reservation(res_id):
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    res = domain.get_reservation(res_id)
    return success_object(domain.serialize(res), status=200)


@bp.route("/backline/reservation-lines", methods=["GET"])
def list_reservations():
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    limit, offset = pagination_params()
    tour_id = request.args.get("tour_id")
    gear_unit_id = request.args.get("gear_unit_id")
    rider_line_id = request.args.get("rider_line_id")
    status = request.args.get("status")
    items = list(store.reservation_lines.values())
    if tour_id is not None:
        items = [r for r in items if r.get("tour_id") == tour_id]
    if gear_unit_id is not None:
        items = [r for r in items if r.get("gear_unit_id") == gear_unit_id]
    if rider_line_id is not None:
        items = [r for r in items if r.get("rider_line_id") == rider_line_id]
    if status is not None:
        items = [r for r in items if r.get("status") == status]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success_list([domain.serialize(r) for r in page], meta, status=200)


@bp.route("/backline/reservation-lines/<res_id>/dispatch", methods=["POST"])
def dispatch_reservation(res_id):
    auth = get_auth()
    require_roles(auth, {"LogisticsCoordinator"})
    res = domain.get_reservation(res_id)
    if res["status"] != "SOURCED":
        raise errors.invalid_state("Reservation must be SOURCED to dispatch")
    tour = domain.get_tour(res["tour_id"])
    if tour["status"] != "ACTIVE":
        raise errors.invalid_state("Parent tour must be ACTIVE to dispatch")
    # At least one PLANNED/LOADING shipment bound for the reservation's destination
    has_leg = any(
        s.get("tour_id") == tour["id"] and s.get("to_city_code") == res["dest_city_code"]
        and s.get("status") in {"PLANNED", "LOADING"}
        for s in store.shipments.values())
    if not has_leg:
        raise errors.invalid_state("No PLANNED/LOADING shipment covers the destination city")
    # Unit RESERVED -> OUT_ON_RENTAL (no-op for cross-rentals, which hold no
    # in-house unit)
    if not res.get("is_cross_rental") and res.get("gear_unit_id"):
        unit = store.gear_units.get(res["gear_unit_id"])
        if unit is not None and unit.get("status") == "RESERVED":
            unit["status"] = "OUT_ON_RENTAL"
            touch(unit)
    res["status"] = "DISPATCHED"
    touch(res)
    return success_object(domain.serialize(res), status=200)


@bp.route("/backline/reservation-lines/<res_id>/mark-delivered", methods=["POST"])
def mark_delivered(res_id):
    auth = get_auth()
    require_roles(auth, {"LogisticsCoordinator"})
    res = domain.get_reservation(res_id)
    if res["status"] != "DISPATCHED":
        raise errors.invalid_state("Reservation must be DISPATCHED to mark delivered")
    res["status"] = "DELIVERED"
    touch(res)
    return success_object(domain.serialize(res), status=200)


@bp.route("/backline/reservation-lines/<res_id>/check-in", methods=["POST"])
def check_in(res_id):
    auth = get_auth()
    require_roles(auth, {"WarehouseTech"})
    res = domain.get_reservation(res_id)
    if res["status"] != "DELIVERED":
        raise errors.invalid_state("Reservation must be DELIVERED to check in")
    data = body()
    if data.get("checked_in_at") is None:
        raise errors.invalid_request("Missing required field: checked_in_at")
    checked_in_dt = parse_datetime(data.get("checked_in_at"), "checked_in_at")
    domain.check_in_reservation(res, checked_in_dt)
    return success_object(domain.serialize(res), status=200)


@bp.route("/backline/reservation-lines/<res_id>/inspect", methods=["POST"])
def inspect(res_id):
    auth = get_auth()
    require_roles(auth, {"WarehouseTech"})
    res = domain.get_reservation(res_id)
    if res["status"] != "RETURNED":
        raise errors.invalid_state("Reservation must be RETURNED to inspect")
    data = body()
    damage_present = opt_bool(data, "damage_present")
    if damage_present is None:
        raise errors.invalid_request("Missing required field: damage_present")
    if damage_present:
        severity = opt_enum(data, "assessed_severity", SEVERITIES)
        if severity is None:
            raise errors.invalid_request("Missing required field: assessed_severity")
        estimate = opt_int(data, "repair_estimate_cents", minimum=0)
        if estimate is None:
            raise errors.invalid_request("Missing required field: repair_estimate_cents")
        # Atomically file the claim; the damaged unit is quarantined (§3.7)
        claim = new_resource()
        claim.update({
            "reservation_line_id": res["id"],
            "gear_unit_id": res.get("gear_unit_id"),
            "assessed_severity": severity,
            "repair_estimate_cents": estimate,
            "status": "FILED",
            "charge_cents": None,
            "filed_by_user_id": auth["user_id"],
            "assessed_at_dt": None,
        })
        store.damage_claims[claim["id"]] = claim
        unit = None
        if res.get("gear_unit_id"):
            unit = store.gear_units.get(res["gear_unit_id"])
        if unit is not None and unit.get("status") in {"OUT_ON_RENTAL", "IN_TRANSIT", "AVAILABLE"}:
            unit["status"] = "QUARANTINED"
            touch(unit)
    res["status"] = "INSPECTED"
    touch(res)
    return success_object(domain.serialize(res), status=200)


@bp.route("/backline/reservation-lines/<res_id>/settle", methods=["POST"])
def settle(res_id):
    auth = get_auth()
    require_roles(auth, {"TourManager"})
    res = domain.get_reservation(res_id)
    # Gate 4: state legality — no open damage claim on this reservation
    if res["status"] != "INSPECTED":
        raise errors.invalid_state("Reservation must be INSPECTED to settle")
    for c in store.damage_claims.values():
        if c.get("reservation_line_id") == res["id"] and \
                c.get("status") in {"FILED", "ASSESSED", "DISPUTED"}:
            raise errors.invalid_state("Open damage claims block settlement")
    # Gate 5: OCC expected_reservation_version
    data = body()
    expected = opt_int(data, "expected_reservation_version")
    if expected is None:
        raise errors.invalid_request("Missing required field: expected_reservation_version")
    if expected != res["version"]:
        raise errors.stale_version("expected_reservation_version does not match current version")
    tour = domain.get_tour(res["tour_id"])
    artist = store.artists.get(tour["artist_id"])
    rider_line = store.rider_lines.get(res["rider_line_id"])
    model = store.gear_models.get(rider_line["gear_model_id"]) if rider_line else None
    days = day_count(res["_start_dt"], res["_end_dt"])
    if res.get("is_cross_rental"):
        base_rate = res.get("_vendor_rate_cents_per_day") or 0
    else:
        base_rate = model["daily_rate_cents"] if model else 0
    was_shorted = domain.rider_line_was_shorted(res["rider_line_id"])
    settled = calc.rental_fee_settlement(
        base_rate, days, res["origin_city_code"], res["dest_city_code"],
        artist.get("risk_score", 0), res["_end_dt"], res.get("_checked_in_dt"),
        was_shorted)
    res["settled_fee_cents"] = settled
    # Release the hold diminished by any PAID damage charges on this reservation
    paid_charges = sum(
        c.get("charge_cents") or 0
        for c in store.damage_claims.values()
        if c.get("reservation_line_id") == res["id"] and c.get("status") == "PAID")
    release_amount = (res.get("deposit_held_cents") or 0) - paid_charges
    artist["deposit_credit_cents"] = artist.get("deposit_credit_cents", 0) + release_amount
    touch(artist)
    res["deposit_held_cents"] = 0
    res["status"] = "SETTLED"
    touch(res)
    return success_object(domain.serialize(res), status=200)


@bp.route("/backline/reservation-lines/<res_id>/cancel", methods=["POST"])
def cancel_reservation(res_id):
    auth = get_auth()
    require_roles(auth, {"TourManager"})
    res = domain.get_reservation(res_id)
    if res["status"] not in {"DRAFT", "SOURCED"}:
        raise errors.invalid_state("Only DRAFT or SOURCED reservations may be cancelled")
    domain.release_reservation(res)
    res["status"] = "CANCELLED"
    touch(res)
    return success_object(domain.serialize(res), status=200)
