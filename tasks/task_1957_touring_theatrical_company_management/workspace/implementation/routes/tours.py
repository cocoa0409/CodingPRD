"""Tour endpoints: POST /tours, GET /tours/{id}, PATCH /tours/{id}."""

from flask import Blueprint

import db
from db import touch
from errors import (err, ERR_NOT_FOUND, ERR_TOUR_INVALID_STATE)
from middleware import authenticate, require_roles
from response import success
from services import domain
from util import (get_body, reject_unknown, require_present, as_int, as_str,
                  as_enum)

bp = Blueprint("tours", __name__)

TOUR_STATUSES = ("PLANNING", "ON_TOUR", "COMPLETED", "CLOSED")


@bp.route("/tours", methods=["POST"])
def create_tour():
    _, role = authenticate()
    require_roles(role, ("Producer",))
    body = get_body()
    reject_unknown(body, {"name", "budget_total_cents", "capitalization_cents",
                          "per_diem_policy", "per_diem_daily_cents",
                          "royalty_tier_threshold_cents"})
    name = as_str(require_present(body, "name"), "name")
    budget = as_int(require_present(body, "budget_total_cents"),
                    "budget_total_cents", minv=0)
    cap = as_int(require_present(body, "capitalization_cents"),
                 "capitalization_cents", minv=0)
    policy = as_enum(require_present(body, "per_diem_policy"), "per_diem_policy",
                     ("FULL_WEEK", "ACTUAL_DAYS"))
    rate = as_int(require_present(body, "per_diem_daily_cents"),
                  "per_diem_daily_cents", minv=1)
    threshold = as_int(require_present(body, "royalty_tier_threshold_cents"),
                       "royalty_tier_threshold_cents", minv=1)
    rec = db.new_record()
    rec.update({
        "name": name,
        "budget_total_cents": budget,
        "capitalization_cents": cap,
        "per_diem_policy": policy,
        "per_diem_daily_cents": rate,
        "royalty_tier_threshold_cents": threshold,
        "status": "PLANNING",
        "budget_committed_cents": 0,
        "budget_spent_cents": 0,
        "cumulative_producer_net_cents": 0,
        "recouped": False,
        "royalty_accrued_cents": 0,
    })
    db.tours[rec["id"]] = rec
    return success(db.tour_view(rec), 201)


@bp.route("/tours/<tour_id>", methods=["GET"])
def get_tour(tour_id):
    authenticate()
    tour = db.tours.get(tour_id)
    if tour is None:
        raise err(ERR_NOT_FOUND, 404, "Tour not found")
    return success(db.tour_view(tour), 200)


@bp.route("/tours/<tour_id>", methods=["PATCH"])
def patch_tour(tour_id):
    _, role = authenticate()
    require_roles(role, ("Producer",))
    tour = db.tours.get(tour_id)
    if tour is None:
        raise err(ERR_NOT_FOUND, 404, "Tour not found")
    body = get_body()
    reject_unknown(body, {"status"})
    target = as_enum(require_present(body, "status"), "status", TOUR_STATUSES)

    cur = tour["status"]
    if target == "ON_TOUR":
        if cur != "PLANNING":
            raise err(ERR_TOUR_INVALID_STATE, 409,
                      "ON_TOUR is only reachable from PLANNING")
    elif target == "COMPLETED":
        if cur != "ON_TOUR":
            raise err(ERR_TOUR_INVALID_STATE, 409,
                      "COMPLETED is only reachable from ON_TOUR")
        # Every stop of the tour must be terminal (WRAPPED or CANCELLED).
        for s in domain.stops_of_tour(tour_id):
            if s["booking_status"] not in ("WRAPPED", "CANCELLED"):
                raise err(ERR_TOUR_INVALID_STATE, 409,
                          "Every stop must be WRAPPED or CANCELLED to complete")
    elif target == "CLOSED":
        if cur != "COMPLETED":
            raise err(ERR_TOUR_INVALID_STATE, 409,
                      "CLOSED is only reachable from COMPLETED")
        # Every settlement of the tour must be PAID or VOID.
        for s in domain.stops_of_tour(tour_id):
            st = domain.settlement_of_stop(s["id"])
            if st is not None and st["status"] not in ("PAID", "VOID"):
                raise err(ERR_TOUR_INVALID_STATE, 409,
                          "Every settlement must be PAID or VOID to close")
    else:
        raise err(ERR_TOUR_INVALID_STATE, 409,
                  "No tour transition to status %s" % target)

    tour["status"] = target
    touch(tour)
    return success(db.tour_view(tour), 200)
