"""Tour endpoints (PRD §3.2, §3.9)."""

from flask import Blueprint, request
import errors
from db import store
from middleware import get_auth, require_roles
from response import success_object, success_list
from services import domain, calculations as calc
from util import (body, req_str, opt_str, opt_int, parse_date, new_resource, touch,
                  pagination_params, paginate, sort_by_created)

bp = Blueprint("tours", __name__)

READ_ROLES = {"OpsManager", "TourManager", "LogisticsCoordinator", "WarehouseTech"}


@bp.route("/backline/tours", methods=["POST"])
def create_tour():
    auth = get_auth()
    require_roles(auth, {"TourManager"})
    data = body()
    artist_id = req_str(data, "artist_id")
    # Referenced artist must exist before the tour is created
    domain.get_artist(artist_id)
    start_dt = parse_date(data.get("start_date"), "start_date") if data.get("start_date") is not None else None
    end_dt = parse_date(data.get("end_date"), "end_date") if data.get("end_date") is not None else None
    if start_dt is None:
        raise errors.invalid_request("Missing required field: start_date")
    if end_dt is None:
        raise errors.invalid_request("Missing required field: end_date")
    if end_dt < start_dt:
        raise errors.invalid_window("end_date must be >= start_date")
    tour = new_resource()
    tour.update({
        "artist_id": artist_id,
        "name": req_str(data, "name"),
        "status": "DRAFT",
        "start_date": data.get("start_date"),
        "end_date": data.get("end_date"),
        "insurance_policy_id": opt_str(data, "insurance_policy_id", default=None),
        "projected_rental_fee_cents": 0,
        "final_settlement_cents": 0,
        "stop_count": 0,
    })
    store.tours[tour["id"]] = tour
    return success_object(domain.serialize(tour), status=201)


@bp.route("/backline/tours/<tour_id>", methods=["GET"])
def fetch_tour(tour_id):
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    tour = domain.get_tour(tour_id)
    return success_object(domain.serialize(tour), status=200)


@bp.route("/backline/tours", methods=["GET"])
def list_tours():
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    limit, offset = pagination_params()
    artist_id = request.args.get("artist_id")
    status = request.args.get("status")
    items = list(store.tours.values())
    if artist_id is not None:
        items = [t for t in items if t.get("artist_id") == artist_id]
    if status is not None:
        items = [t for t in items if t.get("status") == status]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success_list([domain.serialize(t) for t in page], meta, status=200)


@bp.route("/backline/tours/<tour_id>/activate", methods=["POST"])
def activate_tour(tour_id):
    auth = get_auth()
    require_roles(auth, {"TourManager"})
    tour = domain.get_tour(tour_id)
    # Gate 4: state legality
    if tour["status"] != "DRAFT":
        raise errors.invalid_state("Tour must be DRAFT to activate")
    # Gate 5: OCC expected_tour_version (non-optional per PRD §2.10)
    data = body()
    expected = opt_int(data, "expected_tour_version")
    if expected is None:
        raise errors.invalid_request("Missing required field: expected_tour_version")
    if expected != tour["version"]:
        raise errors.stale_version("expected_tour_version does not match current version")
    # Business preconditions: >= 1 PLANNED stop
    has_planned_stop = any(
        s.get("tour_id") == tour["id"] and s.get("status") == "PLANNED"
        for s in store.tour_stops.values())
    if not has_planned_stop:
        raise errors.invalid_state("Tour requires at least one PLANNED stop to activate")
    # Gate 14: deposit aggregate re-evaluated at activation (before insurance, §2.11)
    artist = store.artists.get(tour["artist_id"])
    if artist is not None and artist.get("deposit_credit_cents", 0) < 0:
        raise errors.deposit_insufficient("Artist deposit balance cannot cover held deposits")
    # Gate 15: insurance requirement
    if artist is not None and not artist.get("deposit_waived", False):
        if not tour.get("insurance_policy_id"):
            raise errors.insurance_required("insurance_policy_id required for non-waived artist")
    tour["status"] = "ACTIVE"
    touch(tour)
    domain.recompute_projected_fee(tour)
    return success_object(domain.serialize(tour), status=200)


@bp.route("/backline/tours/<tour_id>/complete", methods=["POST"])
def complete_tour(tour_id):
    auth = get_auth()
    require_roles(auth, {"TourManager"})
    tour = domain.get_tour(tour_id)
    if tour["status"] != "ACTIVE":
        raise errors.invalid_state("Tour must be ACTIVE to complete")
    # Every stop must be SETTLED or CANCELLED
    for s in store.tour_stops.values():
        if s.get("tour_id") == tour["id"] and s.get("status") not in {"SETTLED", "CANCELLED"}:
            raise errors.invalid_state("Every TourStop must be SETTLED or CANCELLED")
    # Every reservation must be SETTLED or CANCELLED
    for r in store.reservation_lines.values():
        if r.get("tour_id") == tour["id"] and r.get("status") not in {"SETTLED", "CANCELLED"}:
            raise errors.invalid_state("Every ReservationLine must be SETTLED or CANCELLED")
    # No open damage claims on the tour's reservation lines
    tour_res_ids = {r["id"] for r in store.reservation_lines.values() if r.get("tour_id") == tour["id"]}
    for c in store.damage_claims.values():
        if c.get("reservation_line_id") in tour_res_ids and \
                c.get("status") in {"FILED", "ASSESSED", "DISPUTED"}:
            raise errors.invalid_state("Open damage claims block tour completion")
    tour["status"] = "COMPLETED"
    # final_settlement_cents: chronological settlement total across the tour's
    # delivered-and-returned (i.e. settled) lines net of credits
    final_total = 0
    for r in store.reservation_lines.values():
        if r.get("tour_id") == tour["id"] and r.get("status") == "SETTLED":
            final_total += r.get("settled_fee_cents") or 0
    tour["final_settlement_cents"] = final_total
    touch(tour)
    return success_object(domain.serialize(tour), status=200)


@bp.route("/backline/tours/<tour_id>/cancel", methods=["POST"])
def cancel_tour(tour_id):
    auth = get_auth()
    require_roles(auth, {"TourManager", "OpsManager"})
    tour = domain.get_tour(tour_id)
    if tour["status"] == "DRAFT":
        # DRAFT cancel belongs to the TourManager
        if auth["role"] != "TourManager":
            raise errors.unauthorized("Only TourManager may cancel a DRAFT tour")
        # Cascade: PLANNED stops -> CANCELLED; their rider lines in
        # {REQUESTED, SOURCED, SUBSTITUTION_PENDING, APPROVED} -> CANCELLED;
        # reservations in DRAFT or SOURCED -> CANCELLED, releasing any physical
        # units the cascade unties (PRD §2.9, §3.2 stop-cancel cascade, §3.9)
        for s in store.tour_stops.values():
            if s.get("tour_id") == tour["id"] and s.get("status") == "PLANNED":
                s["status"] = "CANCELLED"
                touch(s)
                for rl in store.rider_lines.values():
                    if rl.get("tour_stop_id") == s["id"] and rl.get("status") in \
                            {"REQUESTED", "SOURCED", "SUBSTITUTION_PENDING", "APPROVED"}:
                        rl["status"] = "CANCELLED"
                        touch(rl)
        for r in store.reservation_lines.values():
            if r.get("tour_id") == tour["id"] and r.get("status") in {"DRAFT", "SOURCED"}:
                domain.release_reservation(r)
                r["status"] = "CANCELLED"
                touch(r)
        tour["status"] = "CANCELLED"
        touch(tour)
        return success_object(domain.serialize(tour), status=200)
    elif tour["status"] == "ACTIVE":
        # ACTIVE cancel belongs to the OpsManager
        if auth["role"] != "OpsManager":
            raise errors.unauthorized("Only OpsManager may cancel an ACTIVE tour")
        # No reservation may be DISPATCHED or DELIVERED
        for r in store.reservation_lines.values():
            if r.get("tour_id") == tour["id"] and r.get("status") in {"DISPATCHED", "DELIVERED"}:
                raise errors.invalid_state("Cannot cancel ACTIVE tour with dispatched/delivered reservations")
        # Cascade: non-terminal stops -> CANCELLED
        for s in store.tour_stops.values():
            if s.get("tour_id") == tour["id"] and s.get("status") not in {"SETTLED", "CANCELLED"}:
                s["status"] = "CANCELLED"
                touch(s)
        # Cascade: SOURCED reservations -> CANCELLED with unit release +
        # deposit credit-back; released units re-run the maintenance gate
        for r in store.reservation_lines.values():
            if r.get("tour_id") == tour["id"] and r.get("status") == "SOURCED":
                domain.release_reservation(r, run_maintenance_gate=True)
                r["status"] = "CANCELLED"
                touch(r)
        tour["status"] = "CANCELLED"
        touch(tour)
        return success_object(domain.serialize(tour), status=200)
    else:
        raise errors.invalid_state("Tour cannot be cancelled from status %s" % tour["status"])
