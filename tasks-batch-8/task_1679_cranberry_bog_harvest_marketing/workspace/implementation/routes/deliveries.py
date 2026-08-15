"""Delivery endpoints: schedule, get, list, receive, grade, accept, dispute, void.

Acceptance runs the over-quota split, tags the season's OPEN pools, books the
provisional advance, and updates the member quota and pool totals; void is the
exact compensating mirror.
"""
from decimal import Decimal

from flask import Blueprint

from db import store, new_common, touch
from errors import ApiError
from middleware import authenticate, require_roles, forbidden, ANY_ROLE
from response import ok, created, paginate
from services import acceptance, grading, scheduling
from validation import (get_body, req_string, opt_string, req_number, req_date,
                        require_positive, require_nonnegative, require_range,
                        round2, to_decimal)

bp = Blueprint("deliveries", __name__)


def get_delivery_or_404(delivery_id):
    delivery = store.deliveries.get(delivery_id)
    if delivery is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Delivery not found")
    return delivery


def check_station_ownership(delivery, uid):
    if delivery["receiving_station_id"] != uid:
        forbidden("StationOperator may only act on deliveries at their own station")


@bp.post("/coop/deliveries")
def create_delivery():
    body = get_body()
    season_id = req_string(body, "season_id")
    bog_id = req_string(body, "bog_id")
    station_id = req_string(body, "receiving_station_id")
    ticket_id = opt_string(body, "harvest_ticket_id")
    scheduled_date = req_date(body, "scheduled_date")
    expected = require_positive(req_number(body, "expected_barrels"), "expected_barrels")

    uid, role = authenticate()
    require_roles(role, {"GrowerMember"})

    # Existence, left to right, with the bog ownership check (band 3) applied
    # as soon as the bog is resolved.
    season = store.seasons.get(season_id)
    if season is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Season not found")
    bog = store.bogs.get(bog_id)
    if bog is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Bog not found")
    if bog["member_id"] != uid:
        forbidden("GrowerMember may only schedule deliveries for their own bogs")
    station = store.stations.get(station_id)
    if station is None:
        raise ApiError("ERR_NOT_FOUND", 404, "ReceivingStation not found")
    ticket = None
    if ticket_id is not None:
        ticket = store.tickets.get(ticket_id)
        if ticket is None:
            raise ApiError("ERR_NOT_FOUND", 404, "HarvestTicket not found")

    # Band 7: season alignment of the appointment date.
    scheduling.check_date_within_season(season, scheduled_date)
    # Band 8: aggregate station daily capacity (exactly-at-capacity allowed).
    scheduling.check_station_capacity(station, scheduled_date.isoformat(), expected)
    # Band 9: referenced-entity state compatibility (season, bog, ticket).
    if season["status"] != "OPEN":
        raise ApiError("ERR_SEASON_NOT_OPEN", 409, "Season is not OPEN")
    if bog["status"] != "ACTIVE":
        raise ApiError("ERR_BOG_NOT_ACTIVE", 409, "Bog is not ACTIVE")
    if ticket is not None and (ticket["status"] != "APPROVED" or ticket["bog_id"] != bog_id):
        raise ApiError("ERR_TICKET_INVALID", 409,
                       "harvest_ticket_id must reference an APPROVED ticket for this bog")

    delivery = new_common({
        "member_id": uid,
        "season_id": season_id,
        "bog_id": bog_id,
        "receiving_station_id": station_id,
        "harvest_ticket_id": ticket_id,
        "scheduled_date": scheduled_date.isoformat(),
        "expected_barrels": expected,
        "gross_barrels": None,
        "tare_barrels": None,
        "net_barrels": None,
        "color_score": None,
        "firmness_score": None,
        "foreign_matter_pct": None,
        "grade": None,
        "premium_multiplier": None,
        "weighted_barrels": None,
        "quota_applied_barrels": None,
        "over_quota_barrels": None,
        "main_pool_id": None,
        "over_quota_pool_id": None,
        "advance_amount": None,
        "dispute_count": 0,
        "status": "SCHEDULED",
    })
    store.deliveries[delivery["id"]] = delivery
    return created(delivery)


@bp.get("/coop/deliveries/<delivery_id>")
def get_delivery(delivery_id):
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    return ok(get_delivery_or_404(delivery_id))


@bp.get("/coop/deliveries")
def list_deliveries():
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    rows = list(store.deliveries.values())
    rows = paginate.filter(rows, "member_id")
    rows = paginate.filter(rows, "season_id")
    rows = paginate.filter(rows, "bog_id")
    rows = paginate.filter(rows, "receiving_station_id")
    rows = paginate.filter(rows, "main_pool_id")
    rows = paginate.filter(rows, "over_quota_pool_id")
    rows = paginate.filter(rows, "harvest_ticket_id")
    rows = paginate.filter(rows, "status")
    rows = paginate.filter(rows, "scheduled_date")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.post("/coop/deliveries/<delivery_id>/receive")
def receive_delivery(delivery_id):
    body = get_body()
    gross = require_nonnegative(req_number(body, "gross_barrels"), "gross_barrels")
    tare = require_nonnegative(req_number(body, "tare_barrels"), "tare_barrels")

    uid, role = authenticate()
    require_roles(role, {"StationOperator"})

    delivery = get_delivery_or_404(delivery_id)
    check_station_ownership(delivery, uid)

    if delivery["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Delivery transition %s -> RECEIVED is not defined"
                       % delivery["status"])
    if tare > gross:
        raise ApiError("ERR_TARE_EXCEEDS_GROSS", 422,
                       "tare_barrels must not exceed gross_barrels")

    delivery["gross_barrels"] = gross
    delivery["tare_barrels"] = tare
    delivery["net_barrels"] = round2(gross - tare)
    delivery["status"] = "RECEIVED"
    touch(delivery)
    return ok(delivery)


@bp.post("/coop/deliveries/<delivery_id>/grade")
def grade_delivery(delivery_id):
    body = get_body()
    color = require_range(req_number(body, "color_score"), "color_score",
                          Decimal("0"), Decimal("10"))
    firmness = require_range(req_number(body, "firmness_score"), "firmness_score",
                             Decimal("0"), Decimal("10"))
    fm = require_nonnegative(req_number(body, "foreign_matter_pct"), "foreign_matter_pct")

    uid, role = authenticate()
    require_roles(role, {"StationOperator"})

    delivery = get_delivery_or_404(delivery_id)
    check_station_ownership(delivery, uid)

    if delivery["status"] not in ("RECEIVED", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Delivery in %s cannot be graded" % delivery["status"])

    grade, multiplier, weighted = grading.assign_grade(
        color, firmness, fm, delivery["net_barrels"])

    delivery["color_score"] = color
    delivery["firmness_score"] = firmness
    delivery["foreign_matter_pct"] = fm
    delivery["grade"] = grade
    delivery["premium_multiplier"] = multiplier
    delivery["weighted_barrels"] = weighted
    delivery["status"] = "REJECTED" if grade == "REJECT" else "GRADED"
    touch(delivery)
    return ok(delivery)


@bp.post("/coop/deliveries/<delivery_id>/accept")
def accept_delivery(delivery_id):
    _, role = authenticate()
    require_roles(role, {"PoolManager"})

    delivery = get_delivery_or_404(delivery_id)
    if delivery["status"] != "GRADED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Delivery transition %s -> ACCEPTED is not defined"
                       % delivery["status"])

    acceptance.accept_delivery(delivery)
    return ok(delivery)


@bp.post("/coop/deliveries/<delivery_id>/dispute")
def dispute_delivery(delivery_id):
    uid, role = authenticate()
    require_roles(role, {"GrowerMember"})

    delivery = get_delivery_or_404(delivery_id)
    if delivery["member_id"] != uid:
        forbidden("GrowerMember may only dispute their own deliveries")
    if delivery["status"] != "GRADED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Delivery transition %s -> DISPUTED is not defined"
                       % delivery["status"])

    delivery["dispute_count"] = delivery.get("dispute_count", 0) + 1
    delivery["status"] = "DISPUTED"
    touch(delivery)
    return ok(delivery)


@bp.post("/coop/deliveries/<delivery_id>/void")
def void_delivery(delivery_id):
    _, role = authenticate()
    require_roles(role, {"PoolManager"})

    delivery = get_delivery_or_404(delivery_id)
    if delivery["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Delivery transition %s -> VOIDED is not defined"
                       % delivery["status"])

    acceptance.void_delivery(delivery)
    return ok(delivery)
