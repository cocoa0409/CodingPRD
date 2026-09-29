"""The backhaul market -- PRD §3.6."""

from flask import Blueprint, g

import calc
from core import (
    ALL_ROLES, D, apply_filters, auth, bump, by_created, clock_now, dec, fail,
    must_exist, new_row, out, page, respond, db,
)
import validate as v

bp = Blueprint("backhaul", __name__)

READ_ROLES = ALL_ROLES
ORIGIN_KINDS = ("VENDOR_PICKUP", "THIRD_PARTY")
TEMPERATURE_MODES = ("DRY", "REFRIGERATED")
OFFER_STATUSES = ("PROPOSED", "UNDER_REVIEW", "ACCEPTED", "REJECTED", "WITHDRAWN", "EXPIRED")


def _linking_trips(offer_id):
    return [t for t in db.trips.values() if t.get("backhaul_offer_id") == offer_id]


@bp.post("/backhaul-offers")
def create_offer():
    auth(["FleetPlanner"])
    data = v.body()
    v.fk(data, "dest_store_id", "stores")
    origin_kind = v.renum(data, "origin_kind", ORIGIN_KINDS)
    shipper_name = v.rstr(data, "shipper_name")
    origin_region_code = v.rstr(data, "origin_region_code")
    dest_store_id = v.rref(data, "dest_store_id")
    revenue_cents = v.rint(data, "revenue_cents", 1)
    cases = v.rint(data, "cases", 1)
    weight_lbs = v.rint(data, "weight_lbs", 0)
    deadhead_miles = v.rint(data, "deadhead_miles", 0)
    loaded_miles = v.rint(data, "loaded_miles", 0)
    temperature_mode = v.renum(data, "temperature_mode", TEMPERATURE_MODES)
    pickup_start = v.rinstant(data, "pickup_window_start")
    pickup_end = v.rinstant(data, "pickup_window_end")
    v.window_order(pickup_start, pickup_end, "pickup_window_start", "pickup_window_end")
    offer_expires_at = v.rinstant(data, "offer_expires_at")
    row = new_row({
        "origin_kind": origin_kind,
        "shipper_name": shipper_name,
        "origin_region_code": origin_region_code,
        "dest_store_id": dest_store_id,
        "revenue_cents": revenue_cents,
        "cases": cases,
        "weight_lbs": weight_lbs,
        "deadhead_miles": deadhead_miles,
        "loaded_miles": loaded_miles,
        "temperature_mode": temperature_mode,
        "pickup_window_start": pickup_start,
        "pickup_window_end": pickup_end,
        "offer_expires_at": offer_expires_at,
        "status": "PROPOSED",
        "review_round": 0,
        "variable_cost_cents": 0,
        "gross_margin_cents": 0,
        "tier_margin_pct": 0.0,
        "commission_cents": 0,
        "contribution_margin_cents": 0,
        "margin_pct": 0.0,
        "margin_exception_approved": False,
        "created_by_user_id": g.user_id,
    })
    db.offers[row["id"]] = row
    return respond(out(row), 201)


@bp.get("/backhaul-offers/<offer_id>")
def get_offer(offer_id):
    auth(READ_ROLES)
    return respond(out(must_exist("offers", offer_id)))


@bp.get("/backhaul-offers")
def list_offers():
    auth(READ_ROLES)
    limit, offset = v.page_window()
    rows = apply_filters(list(db.offers.values()), [
        ("dest_store_id", v.qstr("dest_store_id")),
        ("origin_kind", v.qenum("origin_kind", ORIGIN_KINDS)),
        ("origin_region_code", v.qstr("origin_region_code")),
        ("status", v.qenum("status", OFFER_STATUSES)),
    ])
    return page(rows, limit, offset)


@bp.post("/backhaul-offers/<offer_id>/submit-review")
def submit_review(offer_id):
    auth(["FleetPlanner"])
    offer = must_exist("offers", offer_id)
    v.body()
    if offer["status"] != "PROPOSED":
        fail("ERR_OFFER_NOT_UNDER_REVIEW")
    if not (clock_now() < D(offer["offer_expires_at"])):
        fail("ERR_INVALID_STATE_TRANSITION", "The offer has already expired.")
    calc.compute_offer_margin(offer)
    offer["status"] = "UNDER_REVIEW"
    bump(offer)
    return respond(out(offer))


@bp.post("/backhaul-offers/<offer_id>/revise")
def revise_offer(offer_id):
    auth(["FleetPlanner"])
    offer = must_exist("offers", offer_id)
    data = v.body()
    revenue_cents = v.oint(data, "revenue_cents", None, 1)
    cases = v.oint(data, "cases", None, 1)
    deadhead_miles = v.oint(data, "deadhead_miles", None, 0)
    loaded_miles = v.oint(data, "loaded_miles", None, 0)
    if offer["status"] != "UNDER_REVIEW":
        fail("ERR_OFFER_NOT_UNDER_REVIEW")
    if int(offer["review_round"]) >= 3:
        fail("ERR_REVIEW_ROUND_LIMIT")
    if revenue_cents is not None:
        offer["revenue_cents"] = revenue_cents
    if cases is not None:
        offer["cases"] = cases
    if deadhead_miles is not None:
        offer["deadhead_miles"] = deadhead_miles
    if loaded_miles is not None:
        offer["loaded_miles"] = loaded_miles
    offer["status"] = "PROPOSED"
    offer["review_round"] = int(offer["review_round"]) + 1
    calc.compute_offer_margin(offer)
    bump(offer)
    for trip in _linking_trips(offer["id"]):
        trip["backhaul_credit_cents"] = 0
        bump(trip)
    return respond(out(offer))


@bp.post("/backhaul-offers/<offer_id>/accept")
def accept_offer(offer_id):
    auth(["TransportManager"])
    offer = must_exist("offers", offer_id)
    data = v.body()
    # level 3: segregation of duties, conditional on the claimed exception
    if data.get("margin_exception_approved") is True:
        if g.user_id == offer["created_by_user_id"]:
            fail("ERR_SEGREGATION_OF_DUTIES")
    exception = v.obool(data, "margin_exception_approved", False)
    # level 8
    if offer["status"] != "UNDER_REVIEW":
        fail("ERR_OFFER_NOT_UNDER_REVIEW")
    linked = _linking_trips(offer["id"])
    if len(linked) != 1 or linked[0]["plan_status"] not in ("PLANNED", "DISPATCHED"):
        fail("ERR_INVALID_STATE_TRANSITION")
    trip = linked[0]
    if offer["temperature_mode"] == "REFRIGERATED":
        trailer = db.trailers.get(trip.get("trailer_id")) if trip.get("trailer_id") else None
        if trailer is None or trailer["trailer_type"] != "REEFER":
            fail("ERR_TEMPERATURE_MODE_MISMATCH")
    # level 16: the contribution-margin floor
    if dec(offer["margin_pct"]) < calc.MIN_MARGIN_PCT and not exception:
        fail("ERR_MARGIN_BELOW_FLOOR")
    offer["margin_exception_approved"] = exception
    offer["status"] = "ACCEPTED"
    bump(offer)
    trip["backhaul_credit_cents"] = int(offer["contribution_margin_cents"])
    bump(trip)
    return respond(out(offer))


@bp.post("/backhaul-offers/<offer_id>/reject")
def reject_offer(offer_id):
    auth(["TransportManager"])
    offer = must_exist("offers", offer_id)
    data = v.body()
    reason = v.ostr(data, "reason_code")
    if offer["status"] != "UNDER_REVIEW":
        fail("ERR_OFFER_NOT_UNDER_REVIEW")
    offer["status"] = "REJECTED"
    offer["_reason_code"] = reason
    bump(offer)
    for trip in _linking_trips(offer["id"]):
        trip["backhaul_offer_id"] = None
        trip["backhaul_credit_cents"] = 0
        bump(trip)
    return respond(out(offer))


@bp.post("/backhaul-offers/<offer_id>/withdraw")
def withdraw_offer(offer_id):
    auth(["FleetPlanner"])
    offer = must_exist("offers", offer_id)
    data = v.body()
    reason = v.ostr(data, "reason_code")
    if offer["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if _linking_trips(offer["id"]):
        fail("ERR_INVALID_STATE_TRANSITION", "A linked offer cannot be withdrawn.")
    offer["status"] = "WITHDRAWN"
    offer["_reason_code"] = reason
    bump(offer)
    return respond(out(offer))


@bp.post("/backhaul-offers/expiration-sweep")
def expiration_sweep():
    auth(["TransportManager"])
    v.body()
    now = clock_now()
    expired_offer_ids = []
    unlinked_trip_ids = []
    for offer in by_created(list(db.offers.values())):
        if offer["status"] not in ("PROPOSED", "UNDER_REVIEW"):
            continue
        if not (D(offer["offer_expires_at"]) <= now):
            continue
        offer["status"] = "EXPIRED"
        bump(offer)
        expired_offer_ids.append(offer["id"])
        for trip in by_created(_linking_trips(offer["id"])):
            trip["backhaul_offer_id"] = None
            trip["backhaul_credit_cents"] = 0
            bump(trip)
            unlinked_trip_ids.append(trip["id"])
    return respond({
        "expired_count": len(expired_offer_ids),
        "expired_offer_ids": expired_offer_ids,
        "unlinked_trip_ids": unlinked_trip_ids,
    })
