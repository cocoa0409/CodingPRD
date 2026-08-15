"""Extension requests: OCC-guarded creation and adjudication."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import api_error, bad_request
from middleware import ALL_ROLES, require_roles
from response import ok, paginate
from services import (authorized_days_total, bump, check_body_fk,
                      claim_of_reservation, create_communication_log,
                      fleet_capacity_exceeded, is_int, new_entity, need_int,
                      opt_str, rental_reserve_cents, require_claim_open,
                      reservation_view, sorted_by_creation, view)
from util import COMPLETION_GRACE_DAYS

bp = Blueprint("extensions", __name__)


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def get_extension(xid):
    x = db.extension_requests.get(xid)
    if x is None:
        raise api_error("ERR_EXTENSION_REQUEST_NOT_FOUND", 404,
                        "extension request not found: %s" % xid)
    return x


@bp.post("/extension-requests")
def create_extension():
    require_roles(["RentalDeskAgent"])
    b = body()
    # rung 4: body FK existence, in payload order
    check_body_fk(b, "reservation_id", db.reservations, "ERR_RESERVATION_NOT_FOUND")
    check_body_fk(b, "milestone_id", db.milestones, "ERR_MILESTONE_NOT_FOUND")
    # shape
    reservation_id = b.get("reservation_id")
    if not isinstance(reservation_id, str) or not reservation_id:
        raise bad_request("reservation_id is required")
    milestone_id = b.get("milestone_id")
    if not isinstance(milestone_id, str) or not milestone_id:
        raise bad_request("milestone_id is required")
    requested = need_int(b, "requested_additional_days")
    if requested < 1:
        raise bad_request("requested_additional_days must be at least 1")
    if not is_int(b.get("expected_reservation_version")):
        raise bad_request("expected_reservation_version is required")
    res = db.reservations[reservation_id]
    milestone = db.milestones[milestone_id]
    claim = claim_of_reservation(res)
    # rung 6
    require_claim_open(claim)
    # rung 8: reservation must be ACTIVE or already under review
    if res["status"] not in ("ACTIVE", "EXTENSION_REVIEW"):
        raise api_error("ERR_RESERVATION_INVALID_STATE", 409,
                        "reservation must be ACTIVE or EXTENSION_REVIEW for an extension")
    # rung 9: OCC on the reservation
    if b["expected_reservation_version"] != res["version"]:
        raise api_error("ERR_STALE_VERSION", 412,
                        "expected_reservation_version does not match the reservation's current version")
    # rung 11: milestone must be a DELAY_REPORTED milestone of the reservation's repair order
    if milestone["milestone_type"] != "DELAY_REPORTED" or milestone["repair_order_id"] != res["repair_order_id"]:
        raise api_error("ERR_EXTENSION_INVALID_STATE", 409,
                        "milestone is not a DELAY_REPORTED milestone of the reservation's repair order")
    # rung 13: duration-cap headroom at creation
    if authorized_days_total(claim) >= claim["coverage_duration_cap_days"]:
        raise api_error("ERR_DURATION_CAP_EXHAUSTED", 409,
                        "no duration-cap headroom remains on the claim")
    # supersede any still-SUBMITTED request on this reservation
    for x in db.extension_requests.values():
        if x["reservation_id"] == reservation_id and x["status"] == "SUBMITTED":
            x["status"] = "SUPERSEDED"
            bump(x)
    if res["status"] == "ACTIVE":
        res["status"] = "EXTENSION_REVIEW"
    bump(res)
    e = new_entity()
    e.update({
        "reservation_id": reservation_id,
        "milestone_id": milestone_id,
        "requested_additional_days": requested,
        "granted_days": None,
        "decision_reason": None,
        "status": "SUBMITTED",
    })
    db.extension_requests[e["id"]] = e
    return ok(view(e), status=201)


@bp.get("/extension-requests")
def list_extensions():
    require_roles(ALL_ROLES)
    items = list(db.extension_requests.values())
    milestone_filter = request.args.get("milestone_id")
    if milestone_filter is not None:
        items = [x for x in items if x["milestone_id"] == milestone_filter]
    page, meta = paginate(sorted_by_creation(items), request.args)
    return ok([view(x) for x in page], response_type="array", pagination=meta)


@bp.get("/extension-requests/<xid>")
def get_one_extension(xid):
    require_roles(ALL_ROLES)
    return ok(view(get_extension(xid)))


@bp.post("/extension-requests/<xid>/approve")
def approve_extension(xid):
    require_roles(["ClaimsAdjuster"])
    ext = get_extension(xid)
    res = db.reservations[ext["reservation_id"]]
    claim = claim_of_reservation(res)
    require_claim_open(claim)
    # state preconditions: request, then reservation, then repair order
    if ext["status"] != "SUBMITTED":
        raise api_error("ERR_EXTENSION_INVALID_STATE", 409,
                        "extension request is not SUBMITTED")
    if res["status"] != "EXTENSION_REVIEW":
        raise api_error("ERR_RESERVATION_INVALID_STATE", 409,
                        "reservation is not EXTENSION_REVIEW")
    order = db.repair_orders[res["repair_order_id"]]
    if order["status"] != "IN_PROGRESS":
        raise api_error("ERR_REPAIR_ORDER_INVALID_STATE", 409,
                        "repair order is not IN_PROGRESS")
    milestone = db.milestones[ext["milestone_id"]]
    # extension_day_grant — pinned evaluation order on pre-grant values
    cap_remaining = claim["coverage_duration_cap_days"] - authorized_days_total(claim)
    if cap_remaining <= 0:
        raise api_error("ERR_DURATION_CAP_EXHAUSTED", 409,
                        "no duration-cap headroom remains on the claim")
    days_needed = max(0, (milestone["new_estimated_completion_date"]
                          + timedelta(days=COMPLETION_GRACE_DAYS)
                          - res["authorized_return_date"]).days)
    if days_needed == 0:
        raise api_error("ERR_EXTENSION_NOT_JUSTIFIED", 409,
                        "the milestone's new estimate does not extend beyond the authorized window plus grace")
    granted = min(ext["requested_additional_days"], cap_remaining, days_needed)
    cost = granted * res["daily_rate_cents"]
    if cost > rental_reserve_cents(claim):
        raise api_error("ERR_INSUFFICIENT_RESERVE", 402,
                        "grant cost exceeds the claim's rental reserve")
    partner = db.rental_partners[res["rental_partner_id"]]
    new_return = res["authorized_return_date"] + timedelta(days=granted)
    if fleet_capacity_exceeded(partner, res["vehicle_class"],
                               res["authorized_return_date"], new_return,
                               exclude_reservation_id=res["id"]):
        raise api_error("ERR_FLEET_CAPACITY_EXCEEDED", 409,
                        "partner fleet capacity exceeded on the added days")
    # apply the grant exactly once
    res["authorized_return_date"] = new_return
    res["authorized_days"] += granted
    res["estimated_charge_cents"] += cost
    res["status"] = "ACTIVE"
    bump(res)
    ext["granted_days"] = granted
    ext["status"] = "APPROVED"
    bump(ext)
    bump(claim)
    create_communication_log(claim["id"], "EMAIL", "EXTENSION_UPDATE",
                             "Rental extension approved.")
    return ok(view(ext))


@bp.post("/extension-requests/<xid>/deny")
def deny_extension(xid):
    require_roles(["ClaimsAdjuster"])
    ext = get_extension(xid)
    res = db.reservations[ext["reservation_id"]]
    claim = claim_of_reservation(res)
    require_claim_open(claim)
    b = body()
    reason = opt_str(b, "decision_reason")
    if ext["status"] != "SUBMITTED":
        raise api_error("ERR_EXTENSION_INVALID_STATE", 409,
                        "extension request is not SUBMITTED")
    if res["status"] != "EXTENSION_REVIEW":
        raise api_error("ERR_RESERVATION_INVALID_STATE", 409,
                        "reservation is not EXTENSION_REVIEW")
    ext["decision_reason"] = reason
    ext["status"] = "DENIED"
    bump(ext)
    res["status"] = "ACTIVE"
    bump(res)
    # denial deliberately does NOT advance the claim's version
    create_communication_log(claim["id"], "EMAIL", "EXTENSION_UPDATE",
                             "Rental extension denied.")
    return ok(view(ext))
