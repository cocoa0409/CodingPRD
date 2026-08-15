"""Rental reservations: booking, authorization, lifecycle, nested collections."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import api_error, bad_request
from middleware import ALL_ROLES, require_roles
from response import ok, paginate
from services import (authorized_days_total, bump, check_body_fk,
                      claim_of_reservation, create_recovery_case,
                      fleet_capacity_exceeded, get_claim, get_reservation,
                      is_int, maybe_rental_track_active,
                      maybe_rental_track_closed, new_entity, need_date,
                      need_enum, rental_reserve_cents, require_claim_open,
                      reservation_view, sorted_by_creation, view)
from util import RETURN_GRACE_DAYS

bp = Blueprint("reservations", __name__)

VEHICLE_CLASSES = ("ECONOMY", "STANDARD", "PREMIUM")


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.post("/rental-reservations")
def create_reservation():
    require_roles(["RentalDeskAgent"])
    b = body()
    # rung 4: body FK existence, in payload order
    check_body_fk(b, "claim_id", db.claims, "ERR_CLAIM_NOT_FOUND")
    check_body_fk(b, "rental_partner_id", db.rental_partners, "ERR_RENTAL_PARTNER_NOT_FOUND")
    check_body_fk(b, "repair_order_id", db.repair_orders, "ERR_REPAIR_ORDER_NOT_FOUND")
    # shape
    claim_id = b.get("claim_id")
    if not isinstance(claim_id, str) or not claim_id:
        raise bad_request("claim_id is required")
    partner_id = b.get("rental_partner_id")
    if not isinstance(partner_id, str) or not partner_id:
        raise bad_request("rental_partner_id is required")
    order_id = b.get("repair_order_id")
    if not isinstance(order_id, str) or not order_id:
        raise bad_request("repair_order_id is required")
    vehicle_class = need_enum(b, "vehicle_class", VEHICLE_CLASSES)
    pickup = need_date(b, "pickup_date")
    authorized_return = need_date(b, "authorized_return_date")
    if not is_int(b.get("expected_claim_version")):
        raise bad_request("expected_claim_version is required")
    claim = get_claim(claim_id)
    partner = db.rental_partners[partner_id]
    order = db.repair_orders[order_id]
    # rung 6
    require_claim_open(claim)
    # rung 7
    if claim["rental_track_status"] != "COVERAGE_VERIFIED":
        raise api_error("ERR_COVERAGE_NOT_VERIFIED", 409,
                        "claim rental track is not COVERAGE_VERIFIED")
    # rung 9: OCC on the claim
    if b["expected_claim_version"] != claim["version"]:
        raise api_error("ERR_STALE_VERSION", 412,
                        "expected_claim_version does not match the claim's current version")
    # rung 10: temporal
    if pickup < db.clock_date():
        raise api_error("ERR_PICKUP_DATE_IN_PAST", 400,
                        "pickup_date is strictly before the current date")
    if authorized_return <= pickup:
        raise api_error("ERR_INVALID_PERIOD", 400,
                        "authorized_return_date must be strictly later than pickup_date")
    # rung 11: referential
    if partner["status"] != "ACTIVE":
        raise api_error("ERR_PARTNER_SUSPENDED", 409, "rental partner is SUSPENDED")
    if order["claim_id"] != claim_id:
        raise api_error("ERR_REPAIR_ORDER_MISMATCH", 409,
                        "repair order does not belong to the reservation's claim")
    if order["status"] not in ("APPROVED", "IN_PROGRESS"):
        raise api_error("ERR_REPAIR_ORDER_INVALID_STATE", 409,
                        "repair order must be APPROVED or IN_PROGRESS")
    # rung 12: half-open overlap with existing reservations on the claim
    for r in db.reservations.values():
        if r["claim_id"] != claim_id:
            continue
        if r["status"] not in ("DRAFT", "AUTHORIZED", "ACTIVE", "EXTENSION_REVIEW"):
            continue
        if pickup < r["authorized_return_date"] and r["pickup_date"] < authorized_return:
            raise api_error("ERR_RESERVATION_PERIOD_OVERLAP", 409,
                            "reservation window overlaps an existing reservation on the claim")
    # rung 12: loss-of-use conflict — reservation window closed on both ends
    for l in db.lou_claims.values():
        if l["claim_id"] != claim_id:
            continue
        if pickup <= l["period_end"] and l["period_start"] <= authorized_return:
            raise api_error("ERR_LOU_PERIOD_CONFLICT", 409,
                            "reservation window conflicts with a loss-of-use period on the claim")
    snapshot = {
        "ECONOMY": partner["economy_rate_cents"],
        "STANDARD": partner["standard_rate_cents"],
        "PREMIUM": partner["premium_rate_cents"],
    }
    days = (authorized_return - pickup).days
    e = new_entity()
    e.update({
        "claim_id": claim_id,
        "rental_partner_id": partner_id,
        "repair_order_id": order_id,
        "vehicle_class": vehicle_class,
        "pickup_date": pickup,
        "authorized_return_date": authorized_return,
        "actual_pickup_date": None,
        "actual_return_date": None,
        "rate_card_snapshot": snapshot,
        "daily_rate_cents": snapshot[vehicle_class],
        "authorized_days": days,
        "consumed_days": None,
        "unnecessary_days": 0,
        "estimated_charge_cents": days * snapshot[vehicle_class],
        "status": "DRAFT",
        "_initial_class": vehicle_class,
    })
    db.reservations[e["id"]] = e
    bump(claim)
    return ok(reservation_view(e), status=201)


@bp.get("/rental-reservations")
def list_reservations():
    require_roles(ALL_ROLES)
    items = list(db.reservations.values())
    partner_filter = request.args.get("rental_partner_id")
    if partner_filter is not None:
        items = [r for r in items if r["rental_partner_id"] == partner_filter]
    order_filter = request.args.get("repair_order_id")
    if order_filter is not None:
        items = [r for r in items if r["repair_order_id"] == order_filter]
    page, meta = paginate(sorted_by_creation(items), request.args)
    return ok([reservation_view(r) for r in page], response_type="array", pagination=meta)


@bp.get("/rental-reservations/<rid>")
def get_one_reservation(rid):
    require_roles(ALL_ROLES)
    return ok(reservation_view(get_reservation(rid)))


@bp.post("/rental-reservations/<rid>/authorize")
def authorize_reservation(rid):
    require_roles(["RentalDeskAgent"])
    res = get_reservation(rid)
    claim = claim_of_reservation(res)
    require_claim_open(claim)
    if res["status"] != "DRAFT":
        raise api_error("ERR_RESERVATION_INVALID_STATE", 409,
                        "only a DRAFT reservation can be authorized")
    # fiscal gates in the pinned order: reserve, then duration cap, then fleet
    if res["estimated_charge_cents"] > rental_reserve_cents(claim):
        raise api_error("ERR_INSUFFICIENT_RESERVE", 402,
                        "estimated charge exceeds the claim's rental reserve")
    if authorized_days_total(claim) + res["authorized_days"] > claim["coverage_duration_cap_days"]:
        raise api_error("ERR_DURATION_CAP_EXHAUSTED", 409,
                        "authorized days would exceed the coverage duration cap")
    partner = db.rental_partners[res["rental_partner_id"]]
    if fleet_capacity_exceeded(partner, res["vehicle_class"],
                               res["pickup_date"], res["authorized_return_date"],
                               exclude_reservation_id=res["id"]):
        raise api_error("ERR_FLEET_CAPACITY_EXCEEDED", 409,
                        "partner fleet capacity exceeded on some day of the window")
    res["status"] = "AUTHORIZED"
    bump(res)
    bump(claim)
    return ok(reservation_view(res))


@bp.post("/rental-reservations/<rid>/activate")
def activate_reservation(rid):
    caller = require_roles(["RentalPartner"])
    res = get_reservation(rid)
    if res["rental_partner_id"] != caller.id:
        raise api_error("ERR_NOT_RESOURCE_OWNER", 403,
                        "caller partner does not own this reservation")
    claim = claim_of_reservation(res)
    require_claim_open(claim)
    if res["status"] != "AUTHORIZED":
        raise api_error("ERR_RESERVATION_INVALID_STATE", 409,
                        "only an AUTHORIZED reservation can be activated")
    if db.clock_date() < res["pickup_date"]:
        raise api_error("ERR_ACTIVATION_BEFORE_PICKUP_DATE", 400,
                        "current date is before the pickup date")
    res["status"] = "ACTIVE"
    res["actual_pickup_date"] = db.clock_date()
    bump(res)
    maybe_rental_track_active(claim)
    return ok(reservation_view(res))


@bp.post("/rental-reservations/<rid>/return")
def return_reservation(rid):
    caller = require_roles(["RentalPartner"])
    res = get_reservation(rid)
    if res["rental_partner_id"] != caller.id:
        raise api_error("ERR_NOT_RESOURCE_OWNER", 403,
                        "caller partner does not own this reservation")
    claim = claim_of_reservation(res)
    require_claim_open(claim)
    if res["status"] not in ("ACTIVE", "EXTENSION_REVIEW"):
        raise api_error("ERR_RESERVATION_INVALID_STATE", 409,
                        "only an ACTIVE or EXTENSION_REVIEW reservation can be returned")
    if any(x["reservation_id"] == rid and x["status"] == "SUBMITTED"
           for x in db.extension_requests.values()):
        raise api_error("ERR_PENDING_EXTENSION_EXISTS", 409,
                        "a SUBMITTED extension request exists on this reservation")
    res["status"] = "RETURNED"
    res["actual_return_date"] = db.clock_date()
    res["consumed_days"] = (res["actual_return_date"] - res["actual_pickup_date"]).days
    bump(res)
    # unnecessary_rental_days_assessment
    order = db.repair_orders[res["repair_order_id"]]
    if order["status"] != "COMPLETED":
        res["unnecessary_days"] = 0
    else:
        grace_end = order["actual_completion_date"] + timedelta(days=RETURN_GRACE_DAYS)
        unnecessary = max(0, (res["actual_return_date"] - grace_end).days)
        res["unnecessary_days"] = unnecessary
        if unnecessary > 0:
            assessed = unnecessary * res["daily_rate_cents"]
            create_recovery_case(claim, res, "RETURN_OVERSTAY", unnecessary, assessed)
            bump(claim)
    return ok(reservation_view(res))


@bp.post("/rental-reservations/<rid>/close")
def close_reservation(rid):
    require_roles(["RentalDeskAgent"])
    res = get_reservation(rid)
    claim = claim_of_reservation(res)
    require_claim_open(claim)
    if res["status"] != "RETURNED":
        raise api_error("ERR_RESERVATION_INVALID_STATE", 409,
                        "only a RETURNED reservation can be closed")
    if any(inv["reservation_id"] == rid and inv["status"] != "SETTLED"
           for inv in db.invoices.values()):
        raise api_error("ERR_RESERVATION_CLOSE_BLOCKED", 409,
                        "an invoice for this reservation is not SETTLED")
    if any(rc["reservation_id"] == rid and rc["status"] not in ("CLOSED", "WAIVED")
           for rc in db.recovery_cases.values()):
        raise api_error("ERR_RESERVATION_CLOSE_BLOCKED", 409,
                        "a recovery case for this reservation is not resolved")
    res["status"] = "CLOSED"
    bump(res)
    maybe_rental_track_closed(claim)
    return ok(reservation_view(res))


@bp.post("/rental-reservations/<rid>/cancel")
def cancel_reservation(rid):
    require_roles(["RentalDeskAgent"])
    res = get_reservation(rid)
    claim = claim_of_reservation(res)
    require_claim_open(claim)
    if res["status"] not in ("DRAFT", "AUTHORIZED"):
        raise api_error("ERR_RESERVATION_INVALID_STATE", 409,
                        "only a DRAFT or AUTHORIZED reservation can be cancelled")
    res["status"] = "CANCELLED"
    bump(res)
    bump(claim)
    return ok(reservation_view(res))


# ---------------------------------------------------------------------------
# Nested reservation collections
# ---------------------------------------------------------------------------


@bp.get("/rental-reservations/<rid>/extension-requests")
def list_reservation_extensions(rid):
    require_roles(ALL_ROLES)
    get_reservation(rid)
    items = [x for x in db.extension_requests.values() if x["reservation_id"] == rid]
    page, meta = paginate(sorted_by_creation(items), request.args)
    return ok([view(x) for x in page], response_type="array", pagination=meta)


@bp.get("/rental-reservations/<rid>/class-changes")
def list_reservation_class_changes(rid):
    require_roles(ALL_ROLES)
    get_reservation(rid)
    items = [c for c in db.class_changes.values() if c["reservation_id"] == rid]
    page, meta = paginate(sorted_by_creation(items), request.args)
    return ok([view(c) for c in page], response_type="array", pagination=meta)


@bp.get("/rental-reservations/<rid>/invoices")
def list_reservation_invoices(rid):
    require_roles(ALL_ROLES)
    get_reservation(rid)
    items = [i for i in db.invoices.values() if i["reservation_id"] == rid]
    page, meta = paginate(sorted_by_creation(items), request.args)
    return ok([view(i) for i in page], response_type="array", pagination=meta)
