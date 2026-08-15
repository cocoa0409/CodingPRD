"""Stop endpoints: create (OCC on Tour.version), read, transition, amend (OCC).

Pipeline order (PRD §2.8): auth -> role -> existence -> shape -> OCC ->
state -> business safety -> uniqueness -> temporal -> referential -> fiscal.
"""

from datetime import timedelta

from flask import Blueprint, request

import db
from db import touch
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_STALE_VERSION,
                    ERR_TOUR_NOT_BOOKABLE, ERR_STOP_INVALID_STATE,
                    ERR_STOP_NOT_COMPLIANT, ERR_WRAP_NOT_READY,
                    ERR_STOP_WINDOW_CONFLICT, ERR_TOUR_BUDGET_EXCEEDED)
from middleware import authenticate, require_roles
from response import success, success_list
from services import domain, calc
from util import (get_body, reject_unknown, require_present, as_int, as_str,
                  as_number, as_enum, parse_iso_date, paginate)

bp = Blueprint("stops", __name__)

BOOKING_STATUSES = ("TENTATIVE", "CONTRACTED", "ADVANCED", "READY", "PLAYING",
                    "CLOSED", "WRAPPED", "CANCELLED")


def _get_tour_or_404(tour_id):
    tour = db.tours.get(tour_id)
    if tour is None:
        raise err(ERR_NOT_FOUND, 404, "Tour not found")
    return tour


def _get_stop_or_404(stop_id):
    stop = db.stops.get(stop_id)
    if stop is None:
        raise err(ERR_NOT_FOUND, 404, "Stop not found")
    return stop


def _budget_available(tour):
    return (tour["budget_total_cents"] - tour["budget_committed_cents"]
            - tour["budget_spent_cents"])


# --- Create ---------------------------------------------------------------------
@bp.route("/tours/<tour_id>/stops", methods=["POST"])
def create_stop(tour_id):
    _, role = authenticate()
    require_roles(role, ("TourManager",))
    tour = _get_tour_or_404(tour_id)                       # existence (path)
    body = get_body()
    # Existence (body FK) — evaluated before shape when the key is present.
    venue = None
    if "venue_id" in body and body["venue_id"] is not None:
        venue = db.venues.get(body["venue_id"]) if isinstance(body["venue_id"], str) else None
        if venue is None:
            raise err(ERR_NOT_FOUND, 404, "Venue not found")
    reject_unknown(body, {"venue_id", "play_week_start", "play_week_end",
                          "load_in_date", "travel_in_days", "guarantee_cents",
                          "split_pct", "expected_tour_version",
                          "advance_sales_cents"})
    venue_id = as_str(require_present(body, "venue_id"), "venue_id")
    if venue is None:
        venue = db.venues.get(venue_id)
        if venue is None:
            raise err(ERR_NOT_FOUND, 404, "Venue not found")
    pws_raw = require_present(body, "play_week_start")
    pwe_raw = require_present(body, "play_week_end")
    li_raw = require_present(body, "load_in_date")
    pws = parse_iso_date(pws_raw, "play_week_start")
    pwe = parse_iso_date(pwe_raw, "play_week_end")
    li = parse_iso_date(li_raw, "load_in_date")
    travel = as_int(require_present(body, "travel_in_days"), "travel_in_days", minv=0)
    guarantee = as_int(require_present(body, "guarantee_cents"), "guarantee_cents", minv=0)
    split = as_number(require_present(body, "split_pct"), "split_pct", minv=0, maxv=100)
    expected = as_int(require_present(body, "expected_tour_version"),
                      "expected_tour_version")
    advance = as_int(body.get("advance_sales_cents", 0), "advance_sales_cents", minv=0)
    if pwe < pws:
        raise err(ERR_INVALID_REQUEST, 400,
                  "play_week_end must be on or after play_week_start")
    if li > pws:
        raise err(ERR_INVALID_REQUEST, 400,
                  "load_in_date must be on or before play_week_start")
    # OCC on Tour.version (PRD §2.6)
    if expected != tour["version"]:
        raise err(ERR_STALE_VERSION, 412,
                  "expected_tour_version does not match the tour's current version")
    # State: tour must be bookable.
    if tour["status"] not in ("PLANNING", "ON_TOUR"):
        raise err(ERR_TOUR_NOT_BOOKABLE, 409,
                  "Stops may only be added while the tour is PLANNING or ON_TOUR")
    # Temporal: routing window with mandatory travel buffer vs every
    # non-CANCELLED sibling stop (closed intervals; equality on the passing side).
    for sib in domain.stops_of_tour(tour_id):
        if sib["booking_status"] == "CANCELLED":
            continue
        b_start = parse_iso_date(sib["play_week_start"], "play_week_start")
        b_end = parse_iso_date(sib["play_week_end"], "play_week_end")
        after = pws > b_end + timedelta(days=travel)
        before = b_start > pwe + timedelta(days=sib["travel_in_days"])
        if not (after or before):
            raise err(ERR_STOP_WINDOW_CONFLICT, 422,
                      "Routing window conflicts with another stop (travel buffer)")

    rec = db.new_record()
    rec.update({
        "tour_id": tour_id,
        "venue_id": venue_id,
        "play_week_start": pws_raw,
        "play_week_end": pwe_raw,
        "load_in_date": li_raw,
        "travel_in_days": travel,
        "guarantee_cents": guarantee,
        "split_pct": split,
        "advance_sales_cents": advance,
        "booking_status": "TENTATIVE",
        "compliance_status": "PENDING",
        "estimated_venue_payment_cents": None,
        "cancellation_penalty_cents": 0,
        "wrapped_total_cents": None,
    })
    db.stops[rec["id"]] = rec
    touch(tour)  # stop creation increments Tour.version by 1
    return success(db.serialize("stop", rec), 201)


# --- Read ------------------------------------------------------------------------
@bp.route("/stops", methods=["GET"])
def list_stops():
    authenticate()
    items = list(db.stops.values())
    tour_id = request.args.get("tour_id")
    venue_id = request.args.get("venue_id")
    status = request.args.get("status")
    if tour_id is not None:
        items = [s for s in items if s["tour_id"] == tour_id]
    if venue_id is not None:
        items = [s for s in items if s["venue_id"] == venue_id]
    if status is not None:
        items = [s for s in items if s["booking_status"] == status]
    items.sort(key=lambda s: s["_seq"])
    data, total, limit, offset = paginate(items, lambda r: db.serialize("stop", r))
    return success_list(data, total, limit, offset, 200)


@bp.route("/stops/<stop_id>", methods=["GET"])
def get_stop(stop_id):
    authenticate()
    stop = _get_stop_or_404(stop_id)
    return success(db.serialize("stop", stop), 200)


# --- Transitions -------------------------------------------------------------------
@bp.route("/stops/<stop_id>", methods=["PUT"])
def put_stop(stop_id):
    _, role = authenticate()
    body = get_body()
    # Role-for-transition on this shared transition endpoint (priority 2).
    target = body.get("status")
    if target in ("CONTRACTED", "WRAPPED", "CANCELLED"):
        require_roles(role, ("Producer",))
    elif target in ("ADVANCED", "READY"):
        require_roles(role, ("TourManager",))
    else:
        require_roles(role, ("Producer", "TourManager"))
    stop = _get_stop_or_404(stop_id)
    reject_unknown(body, {"status"})
    target = as_enum(require_present(body, "status"), "status", BOOKING_STATUSES)
    tour = db.tours[stop["tour_id"]]
    cur = stop["booking_status"]

    if target == "CONTRACTED":
        if cur != "TENTATIVE":
            raise err(ERR_STOP_INVALID_STATE, 409,
                      "CONTRACTED is only reachable from TENTATIVE")
        if tour["status"] not in ("PLANNING", "ON_TOUR"):
            raise err(ERR_STOP_INVALID_STATE, 409,
                      "Tour is not bookable for contracting")
        # Fiscal gate (priority 10): available must cover the guarantee.
        if _budget_available(tour) < stop["guarantee_cents"]:
            raise err(ERR_TOUR_BUDGET_EXCEEDED, 422,
                      "Tour budget_available_cents is below the guarantee")
        stop["booking_status"] = "CONTRACTED"
        touch(stop)
        tour["budget_committed_cents"] += stop["guarantee_cents"]
        touch(tour)
    elif target == "ADVANCED":
        if cur != "CONTRACTED":
            raise err(ERR_STOP_INVALID_STATE, 409,
                      "ADVANCED is only reachable from CONTRACTED")
        stop["booking_status"] = "ADVANCED"
        touch(stop)
    elif target == "READY":
        if cur != "ADVANCED":
            raise err(ERR_STOP_INVALID_STATE, 409,
                      "READY is only reachable from ADVANCED")
        if stop["compliance_status"] != "COMPLIANT":
            raise err(ERR_STOP_NOT_COMPLIANT, 409,
                      "Certification requires compliance_status COMPLIANT")
        # Freeze the provisional estimate (calc_provisional_settlement_estimate).
        stop["estimated_venue_payment_cents"] = calc.calc_provisional_settlement_estimate(
            stop["guarantee_cents"], stop["split_pct"], stop["advance_sales_cents"])
        stop["booking_status"] = "READY"
        touch(stop)
    elif target == "WRAPPED":
        if cur != "CLOSED":
            raise err(ERR_STOP_INVALID_STATE, 409,
                      "WRAPPED is only reachable from CLOSED")
        settlement = domain.settlement_of_stop(stop_id)
        if settlement is None or settlement["status"] != "PAID":
            raise err(ERR_WRAP_NOT_READY, 409,
                      "The stop's settlement must be PAID before wrap")
        domain.wrap_stop(stop, tour)
    elif target == "CANCELLED":
        if cur not in ("TENTATIVE", "CONTRACTED", "ADVANCED", "READY"):
            raise err(ERR_STOP_INVALID_STATE, 409,
                      "CANCELLED is only reachable from TENTATIVE/CONTRACTED/ADVANCED/READY")
        domain.cancel_stop(stop, tour)
    else:
        # TENTATIVE / PLAYING / CLOSED are never client-reachable targets.
        raise err(ERR_STOP_INVALID_STATE, 409,
                  "No booking_status transition to %s" % target)
    return success(db.serialize("stop", stop), 200)


# --- Amend ---------------------------------------------------------------------------
@bp.route("/stops/<stop_id>/amend", methods=["POST"])
def amend_stop(stop_id):
    _, role = authenticate()
    require_roles(role, ("Producer",))
    stop = _get_stop_or_404(stop_id)
    body = get_body()
    TERMS = ("guarantee_cents", "split_pct", "load_in_date", "travel_in_days")
    reject_unknown(body, {"expected_stop_version"} | set(TERMS))
    expected = as_int(require_present(body, "expected_stop_version"),
                      "expected_stop_version")
    if not any(k in body for k in TERMS):
        raise err(ERR_INVALID_REQUEST, 400,
                  "An amendment requires at least one term field")
    new = {}
    if "guarantee_cents" in body:
        new["guarantee_cents"] = as_int(body["guarantee_cents"], "guarantee_cents", minv=0)
    if "split_pct" in body:
        new["split_pct"] = as_number(body["split_pct"], "split_pct", minv=0, maxv=100)
    if "load_in_date" in body:
        li = parse_iso_date(body["load_in_date"], "load_in_date")
        pws = parse_iso_date(stop["play_week_start"], "play_week_start")
        if li > pws:
            raise err(ERR_INVALID_REQUEST, 400,
                      "load_in_date must be on or before play_week_start")
        new["load_in_date"] = body["load_in_date"]
    if "travel_in_days" in body:
        new["travel_in_days"] = as_int(body["travel_in_days"], "travel_in_days", minv=0)
    # OCC on Stop.version (PRD §2.6)
    if expected != stop["version"]:
        raise err(ERR_STALE_VERSION, 412,
                  "expected_stop_version does not match the stop's current version")
    if stop["booking_status"] != "CONTRACTED":
        raise err(ERR_STOP_INVALID_STATE, 409,
                  "Amendments are only allowed while the stop is CONTRACTED")
    tour = db.tours[stop["tour_id"]]
    delta = 0
    if "guarantee_cents" in new:
        delta = new["guarantee_cents"] - stop["guarantee_cents"]
    if delta > 0 and _budget_available(tour) < delta:
        raise err(ERR_TOUR_BUDGET_EXCEEDED, 422,
                  "Tour budget_available_cents is below the guarantee increase")
    for k, v in new.items():
        stop[k] = v
    touch(stop)
    if delta != 0:
        tour["budget_committed_cents"] += delta
        touch(tour)
    return success(db.serialize("stop", stop), 200)
