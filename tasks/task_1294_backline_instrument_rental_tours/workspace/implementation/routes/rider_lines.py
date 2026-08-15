"""RiderLine endpoints (PRD §3.2, §3.3, §3.4)."""

from flask import Blueprint, request
import errors
from db import store
from middleware import get_auth, require_roles
from response import success_object, success_list
from services import domain, calculations as calc
from util import (body, req_str, opt_str, opt_int, opt_bool, parse_date, new_resource,
                  touch, pagination_params, paginate, sort_by_created)

bp = Blueprint("rider_lines", __name__)

READ_ROLES = {"OpsManager", "TourManager", "LogisticsCoordinator", "WarehouseTech"}


def _bump_stop_revision(stop):
    """Every rider-line mutation on a stop advances rider_revision and bumps
    the stop's version (PRD §3.2)."""
    stop["rider_revision"] = stop.get("rider_revision", 0) + 1
    touch(stop)


@bp.route("/backline/tour-stops/<stop_id>/rider-lines", methods=["POST"])
def create_rider_line(stop_id):
    auth = get_auth()
    require_roles(auth, {"TourManager"})
    stop = domain.get_stop(stop_id)
    data = body()
    gear_model_id = req_str(data, "gear_model_id")
    domain.get_gear_model(gear_model_id)
    quantity = opt_int(data, "quantity")
    if quantity is None:
        raise errors.invalid_request("Missing required field: quantity")
    if quantity < 1:
        raise errors.invalid_request("quantity must be >= 1")
    substitution_of_line_id = opt_str(data, "substitution_of_line_id", default=None)
    if substitution_of_line_id is not None:
        domain.get_rider_line(substitution_of_line_id)
    line = new_resource()
    line.update({
        "tour_stop_id": stop["id"],
        "gear_model_id": gear_model_id,
        "quantity": quantity,
        "status": "REQUESTED",
        "fulfilled_by_reservation_id": None,
        "substitution_of_line_id": substitution_of_line_id,
        "substitution_reason": opt_str(data, "substitution_reason", default=None),
    })
    store.rider_lines[line["id"]] = line
    _bump_stop_revision(stop)
    return success_object(domain.serialize(line), status=201)


@bp.route("/backline/tour-stops/<stop_id>/rider-lines", methods=["GET"])
def list_rider_lines_of_stop(stop_id):
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    domain.get_stop(stop_id)
    limit, offset = pagination_params()
    status = request.args.get("status")
    items = [rl for rl in store.rider_lines.values() if rl.get("tour_stop_id") == stop_id]
    if status is not None:
        items = [rl for rl in items if rl.get("status") == status]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success_list([domain.serialize(rl) for rl in page], meta, status=200)


@bp.route("/backline/rider-lines", methods=["GET"])
def list_rider_lines():
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    limit, offset = pagination_params()
    gear_model_id = request.args.get("gear_model_id")
    fulfilled_by = request.args.get("fulfilled_by_reservation_id")
    substitution_of = request.args.get("substitution_of_line_id")
    status = request.args.get("status")
    items = list(store.rider_lines.values())
    if gear_model_id is not None:
        items = [rl for rl in items if rl.get("gear_model_id") == gear_model_id]
    if fulfilled_by is not None:
        items = [rl for rl in items if rl.get("fulfilled_by_reservation_id") == fulfilled_by]
    if substitution_of is not None:
        items = [rl for rl in items if rl.get("substitution_of_line_id") == substitution_of]
    if status is not None:
        items = [rl for rl in items if rl.get("status") == status]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success_list([domain.serialize(rl) for rl in page], meta, status=200)


@bp.route("/backline/rider-lines/<line_id>", methods=["GET"])
def fetch_rider_line(line_id):
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    line = domain.get_rider_line(line_id)
    return success_object(domain.serialize(line), status=200)


@bp.route("/backline/rider-lines/<line_id>/source", methods=["POST"])
def source_rider_line(line_id):
    auth = get_auth()
    require_roles(auth, {"LogisticsCoordinator"})
    line = domain.get_rider_line(line_id)
    # Gate 4: state legality
    if line["status"] != "REQUESTED":
        raise errors.invalid_state("Rider line must be REQUESTED to source")
    stop = domain.get_stop(line["tour_stop_id"])
    if stop["status"] != "PLANNED":
        raise errors.invalid_state("Parent stop must be PLANNED to source")
    data = body()
    origin_city = req_str(data, "origin_city_code")
    dest_city = req_str(data, "dest_city_code")
    if data.get("start_date") is None:
        raise errors.invalid_request("Missing required field: start_date")
    if data.get("end_date") is None:
        raise errors.invalid_request("Missing required field: end_date")
    start_dt = parse_date(data.get("start_date"), "start_date")
    end_dt = parse_date(data.get("end_date"), "end_date")
    use_cross_rental = opt_bool(data, "use_cross_rental", default=False)
    partner_vendor_id = opt_str(data, "partner_vendor_id", default=None)
    vendor_rate = opt_int(data, "vendor_rate_cents_per_day", default=None, minimum=0)
    # Gate 9: reservation start must strictly precede end
    if end_dt <= start_dt:
        raise errors.invalid_window("Reservation start_date must precede end_date")

    tour = domain.get_tour(stop["tour_id"])
    artist = store.artists.get(tour["artist_id"])

    # Cross-rental path (PRD §3.8): the coordinator routes the demand to a
    # partner vendor. The vendor must be APPROVED and cover the stop's city
    # (gate 13); the reservation behind the request holds no in-house unit and
    # stays DRAFT until the vendor fulfils the request.
    if use_cross_rental:
        if partner_vendor_id is None:
            raise errors.invalid_request("Missing required field: partner_vendor_id")
        vendor = store.partner_vendors.get(partner_vendor_id)
        if vendor is None:
            raise errors.not_found("PartnerVendor not found")
        if vendor.get("status") != "APPROVED" or \
                stop["city_code"] not in (vendor.get("city_codes") or []):
            raise errors.vendor_not_eligible("Vendor not eligible for this cross-rental")
        if vendor_rate is None:
            raise errors.invalid_request("Missing required field: vendor_rate_cents_per_day")
        res = domain.create_draft_cross_rental_reservation(
            tour, line, origin_city, dest_city, start_dt, end_dt, vendor_rate)
        cr = new_resource()
        cr.update({
            "reservation_line_id": res["id"],
            "partner_vendor_id": partner_vendor_id,
            "gear_model_id": line["gear_model_id"],
            "status": "REQUESTED",
            "vendor_rate_cents_per_day": vendor_rate,
            "commission_cents": None,
        })
        store.cross_rental_requests[cr["id"]] = cr
        return success_object(domain.serialize(res), status=200)

    # Candidate selection over the fleet (gates 7 + 8)
    unit, saw_unserviceable = calc.gear_availability_window(
        line["gear_model_id"], start_dt, end_dt, stop["city_code"])

    if unit is None:
        if saw_unserviceable:
            raise errors.unit_not_serviceable(
                "Candidate unit below condition or service-day floor")
        raise errors.gear_unavailable("No unit satisfies the availability window")

    model = store.gear_models.get(line["gear_model_id"])
    deposit = calc.deposit_hold_rule(model["replacement_value_cents"],
                                     artist.get("deposit_waived", False))
    # Gate 14: deposit headroom
    if artist.get("deposit_credit_cents", 0) < deposit:
        raise errors.deposit_insufficient("Artist deposit balance cannot cover the hold")

    res = domain.create_sourced_reservation(
        tour, line, unit, origin_city, dest_city, start_dt, end_dt)
    return success_object(domain.serialize(res), status=200)


@bp.route("/backline/rider-lines/<line_id>/propose-substitution", methods=["POST"])
def propose_substitution(line_id):
    auth = get_auth()
    require_roles(auth, {"LogisticsCoordinator"})
    line = domain.get_rider_line(line_id)
    if line["status"] != "SOURCED":
        raise errors.invalid_state("Rider line must be SOURCED to propose a substitution")
    stop = domain.get_stop(line["tour_stop_id"])
    data = body()
    substitute_model_id = req_str(data, "substitute_gear_model_id")
    domain.get_gear_model(substitute_model_id)
    substitution_reason = req_str(data, "substitution_reason")
    # Gate 8 before gate 10 (§2.11: availability fires before the allowlist):
    # the availability window must yield a candidate of the substitute model
    old_res = store.reservation_lines.get(line.get("fulfilled_by_reservation_id"))
    if old_res is not None:
        unit, _ = calc.gear_availability_window(
            substitute_model_id, old_res["_start_dt"], old_res["_end_dt"],
            stop["city_code"])
        if unit is None:
            raise errors.gear_unavailable(
                "No substitute-model unit satisfies the availability window")
    # Gate 10: substitute must be in the requested model's allowlist
    requested_model = store.gear_models.get(line["gear_model_id"])
    if substitute_model_id not in (requested_model.get("substitute_model_ids") or []):
        raise errors.substitution_not_allowed(
            "Substitute model not in substitute_model_ids")
    line["status"] = "SUBSTITUTION_PENDING"
    line["_substitute_gear_model_id"] = substitute_model_id
    line["substitution_reason"] = substitution_reason
    touch(line)
    _bump_stop_revision(stop)
    return success_object(domain.serialize(line), status=200)


@bp.route("/backline/rider-lines/<line_id>/approve-substitution", methods=["POST"])
def approve_substitution(line_id):
    auth = get_auth()
    require_roles(auth, {"TourManager"})
    line = domain.get_rider_line(line_id)
    if line["status"] != "SUBSTITUTION_PENDING":
        raise errors.invalid_state("Rider line must be SUBSTITUTION_PENDING to approve")
    stop = domain.get_stop(line["tour_stop_id"])
    # Gate 5: OCC on the parent stop's rider_revision
    data = body()
    expected = opt_int(data, "expected_tour_stop_rider_revision")
    if expected is None:
        raise errors.invalid_request("Missing required field: expected_tour_stop_rider_revision")
    if expected != stop.get("rider_revision", 0):
        raise errors.stale_version("expected_tour_stop_rider_revision does not match")
    tour = domain.get_tour(stop["tour_id"])
    artist = store.artists.get(tour["artist_id"])
    substitute_model_id = line.get("_substitute_gear_model_id")
    old_res = store.reservation_lines.get(line.get("fulfilled_by_reservation_id"))
    # Swap executed as paired cancel-and-create (§3.4)
    if old_res is not None:
        domain.release_reservation(old_res)
        old_res["status"] = "CANCELLED"
        touch(old_res)
        # Reserve a unit of the substitute model over the same window
        unit, _ = calc.gear_availability_window(
            substitute_model_id, old_res["_start_dt"], old_res["_end_dt"],
            stop["city_code"])
        if unit is None:
            raise errors.gear_unavailable(
                "No substitute-model unit satisfies the availability window")
        sub_model = store.gear_models.get(substitute_model_id)
        deposit = calc.deposit_hold_rule(sub_model["replacement_value_cents"],
                                         artist.get("deposit_waived", False))
        if artist.get("deposit_credit_cents", 0) < deposit:
            raise errors.deposit_insufficient("Artist deposit balance cannot cover the hold")
        # Create the new reservation against the substitute unit. The rider
        # line now represents the substitute model.
        old_start = old_res["_start_dt"]
        old_end = old_res["_end_dt"]
        origin_city = old_res["origin_city_code"]
        dest_city = old_res["dest_city_code"]
        line["gear_model_id"] = substitute_model_id
        new_res = domain.create_sourced_reservation(
            tour, line, unit, origin_city, dest_city, old_start, old_end)
        # The line lands in APPROVED (create_sourced_reservation set SOURCED)
        line["status"] = "APPROVED"
        touch(line)
        _bump_stop_revision(stop)
    else:
        line["status"] = "APPROVED"
        touch(line)
        _bump_stop_revision(stop)
    line.pop("_substitute_gear_model_id", None)
    return success_object(domain.serialize(line), status=200)


@bp.route("/backline/rider-lines/<line_id>/reject-substitution", methods=["POST"])
def reject_substitution(line_id):
    auth = get_auth()
    require_roles(auth, {"TourManager"})
    line = domain.get_rider_line(line_id)
    if line["status"] != "SUBSTITUTION_PENDING":
        raise errors.invalid_state("Rider line must be SUBSTITUTION_PENDING to reject")
    stop = domain.get_stop(line["tour_stop_id"])
    line["status"] = "SOURCED"
    line.pop("_substitute_gear_model_id", None)
    touch(line)
    _bump_stop_revision(stop)
    return success_object(domain.serialize(line), status=200)


@bp.route("/backline/rider-lines/<line_id>/mark-fulfilled", methods=["POST"])
def mark_fulfilled(line_id):
    auth = get_auth()
    require_roles(auth, {"WarehouseTech"})
    line = domain.get_rider_line(line_id)
    if line["status"] not in {"SOURCED", "APPROVED"}:
        raise errors.invalid_state("Rider line must be SOURCED or APPROVED to mark fulfilled")
    res = store.reservation_lines.get(line.get("fulfilled_by_reservation_id"))
    if res is None or res.get("status") != "DELIVERED":
        raise errors.invalid_state("Linked reservation must be DELIVERED")
    line["status"] = "FULFILLED"
    touch(line)
    return success_object(domain.serialize(line), status=200)


@bp.route("/backline/rider-lines/<line_id>/mark-shorted", methods=["POST"])
def mark_shorted(line_id):
    auth = get_auth()
    require_roles(auth, {"LogisticsCoordinator"})
    line = domain.get_rider_line(line_id)
    if line["status"] != "REQUESTED":
        raise errors.invalid_state("Rider line must be REQUESTED to mark shorted")
    stop = domain.get_stop(line["tour_stop_id"])
    # Empty-pool fallback precondition: availability selector over the stop's
    # venue date window returns empty AND no approved vendor covers the city
    from datetime import timedelta
    venue_dt = parse_date(stop["venue_date"], "venue_date")
    unit, _ = calc.gear_availability_window(
        line["gear_model_id"], venue_dt, venue_dt + timedelta(days=1), stop["city_code"])
    if unit is not None:
        raise errors.invalid_state("A unit is available; the line cannot be marked shorted")
    if calc.approved_vendor_covers_city(stop["city_code"]):
        raise errors.invalid_state("An approved partner vendor covers the stop city")
    line["status"] = "SHORTED"
    touch(line)
    # Shortage credit: model daily rate * quantity for a single stop day,
    # subtracted from the tour's forward-looking projection, floored at 0 (§3.4)
    tour = domain.get_tour(stop["tour_id"])
    model = store.gear_models.get(line["gear_model_id"])
    credit = model["daily_rate_cents"] * line["quantity"] * 1
    tour["projected_rental_fee_cents"] = max(
        0, tour.get("projected_rental_fee_cents", 0) - credit)
    touch(tour)
    return success_object(domain.serialize(line), status=200)


@bp.route("/backline/rider-lines/<line_id>/cancel", methods=["POST"])
def cancel_rider_line(line_id):
    auth = get_auth()
    require_roles(auth, {"TourManager"})
    line = domain.get_rider_line(line_id)
    if line["status"] not in {"REQUESTED", "SOURCED", "SUBSTITUTION_PENDING", "APPROVED"}:
        raise errors.invalid_state("Rider line cannot be cancelled from status %s" % line["status"])
    # Take a linked DRAFT/SOURCED reservation down with the line
    res = store.reservation_lines.get(line.get("fulfilled_by_reservation_id"))
    if res is not None and res.get("status") in {"DRAFT", "SOURCED"}:
        domain.release_reservation(res)
        res["status"] = "CANCELLED"
        touch(res)
    line["status"] = "CANCELLED"
    touch(line)
    return success_object(domain.serialize(line), status=200)
