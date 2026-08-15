"""Hangar offer endpoints: create/list/get/accept/decline. Acceptance atomically
creates the lease, first pro-rated charge, insurance certificate, and primary
aircraft, and bumps Hangar.version (OCC)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from auth import ALL_ROLES, require_ownership, require_roles
from envelope import success_list, success_obj
from errors import (
    ApiError,
    ERR_AIRPORT_NOT_ACTIVE,
    ERR_APPLICATION_NOT_QUEUED,
    ERR_DUPLICATE_N_NUMBER,
    ERR_HANGAR_NOT_AVAILABLE,
    ERR_INSUFFICIENT_COVERAGE,
    ERR_INVALID_REQUEST,
    ERR_NO_ACTIVE_RATE_SCHEDULE,
    ERR_NOT_FOUND,
    ERR_NOT_NEXT_IN_QUEUE,
    ERR_OFFER_NOT_OPEN,
    ERR_OFFER_WINDOW_EXPIRED,
    ERR_SIZE_CLASS_MISMATCH,
    ERR_STALE_VERSION,
)
from services.core import (
    MIN_LIABILITY_COVERAGE_CENTS,
    OCCUPYING_LEASE_STATES,
    covering_certificate,
    create_first_charge,
    hangar_available_for_offer,
    hangar_posture,
    rank_queue,
    select_rate_schedule,
    touch,
)
from timeutil import iso_z, parse_iso
from validators import body, opt_bool, paginate, pagination, req_bool, req_dt, req_int, req_str

bp = Blueprint("offers", __name__)


def get_offer_or_404(offer_id):
    offer = db.offers.get(offer_id)
    if offer is None:
        raise ApiError(ERR_NOT_FOUND, "Offer not found", 404)
    return offer


def n_number_in_use(airport_id, n_number, exclude_aircraft_id=None):
    """Uniqueness scope: aircraft BASED on active-phase leases at the airport."""
    for a in db.aircraft.values():
        if a["status"] != "BASED" or a["n_number"] != n_number:
            continue
        if exclude_aircraft_id is not None and a["id"] == exclude_aircraft_id:
            continue
        lease = db.leases.get(a["lease_id"])
        if lease is None:
            continue
        if lease["airport_id"] == airport_id and lease["status"] in OCCUPYING_LEASE_STATES:
            return True
    return False


@bp.post("/offers")
def create_offer():
    require_roles("AirportManager")
    data = body()
    airport_id = req_str(data, "airport_id")
    hangar_id = req_str(data, "hangar_id")
    application_id = req_str(data, "application_id")
    override = opt_bool(data, "override_next_in_queue", False)

    airport = db.airports.get(airport_id)
    if airport is None:
        raise ApiError(ERR_NOT_FOUND, "Airport not found", 404)
    hangar = db.hangars.get(hangar_id)
    if hangar is None:
        raise ApiError(ERR_NOT_FOUND, "Hangar not found", 404)
    app = db.applications.get(application_id)
    if app is None:
        raise ApiError(ERR_NOT_FOUND, "Application not found", 404)
    if hangar["airport_id"] != airport_id or app["airport_id"] != airport_id:
        raise ApiError(ERR_NOT_FOUND, "Referenced resource is not scoped to this airport", 404)

    # Pipeline: airport-active -> state -> queue rule -> availability -> size -> rate.
    if airport["status"] != "ACTIVE":
        raise ApiError(ERR_AIRPORT_NOT_ACTIVE, "Airport is SUSPENDED", 409)
    if app["status"] != "QUEUED":
        raise ApiError(ERR_APPLICATION_NOT_QUEUED, "Application must be QUEUED to receive an offer", 409)
    if not override:
        ranked = rank_queue(airport_id, hangar["size_class"], db.clock_now())
        if not ranked or ranked[0]["id"] != app["id"]:
            raise ApiError(ERR_NOT_NEXT_IN_QUEUE, "Application is not the highest-ranked eligible QUEUED application", 409)
    if not hangar_available_for_offer(hangar):
        raise ApiError(ERR_HANGAR_NOT_AVAILABLE, "Hangar is not AVAILABLE", 409)
    if hangar["size_class"] != app["size_class_requested"]:
        raise ApiError(ERR_SIZE_CLASS_MISMATCH, "Hangar size_class does not match the application", 409)
    schedule = select_rate_schedule(airport_id, hangar["size_class"], db.clock_now())
    if schedule is None:
        raise ApiError(ERR_NO_ACTIVE_RATE_SCHEDULE, "No ACTIVE rate schedule covers the offer instant", 409)

    now = db.clock_now()
    offer = db.new_entity({
        "airport_id": airport_id,
        "hangar_id": hangar["id"],
        "application_id": app["id"],
        "rate_schedule_id": schedule["id"],
        "quoted_monthly_rate_cents": schedule["monthly_rate_cents"],
        "offer_sent_at": iso_z(now),
        "acceptance_deadline": iso_z(now + timedelta(hours=airport["offer_acceptance_window_hours"])),
        "status": "OPEN",
    })
    db.offers[offer["id"]] = offer
    app["status"] = "OFFERED"
    touch(app)
    # NB: offer creation reserves the hangar but does NOT increment Hangar.version.
    return success_obj(db.public(offer), 201)


@bp.get("/offers")
def list_offers():
    require_roles(*ALL_ROLES)
    items = list(db.offers.values())
    for param in ("airport_id", "hangar_id", "application_id", "rate_schedule_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [o for o in items if o[param] == value]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([db.public(o) for o in page], limit, offset, total)


@bp.get("/offers/<oid>")
def get_offer(oid):
    require_roles(*ALL_ROLES)
    return success_obj(db.public(get_offer_or_404(oid)), 200)


@bp.post("/offers/<oid>/accept")
def accept_offer(oid):
    uid, _role = require_roles("Applicant")
    offer = get_offer_or_404(oid)
    require_ownership(offer["application_id"], uid)
    airport = db.airports[offer["airport_id"]]
    if airport["status"] != "ACTIVE":
        raise ApiError(ERR_AIRPORT_NOT_ACTIVE, "Airport is SUSPENDED", 409)
    if offer["status"] != "OPEN":
        raise ApiError(ERR_OFFER_NOT_OPEN, "Offer must be OPEN to accept", 409)
    now = db.clock_now()
    # Accept boundary is closed: strictly-before required; exactly at the
    # deadline rejects (the lazy sweep only flips the row strictly after).
    if now >= parse_iso(offer["acceptance_deadline"]):
        raise ApiError(ERR_OFFER_WINDOW_EXPIRED, "Acceptance window has closed", 409)

    data = body()
    hangar = db.hangars[offer["hangar_id"]]
    expected_hangar_version = req_int(data, "expected_hangar_version")
    if expected_hangar_version != hangar["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_hangar_version does not match the hangar's current version", 412)
    if hangar["status"] != "OPERATIONAL" or hangar_posture(hangar) != "AVAILABLE":
        raise ApiError(ERR_HANGAR_NOT_AVAILABLE, "Hangar no longer reflects this offer's reservation", 409)

    attested = req_bool(data, "aeronautical_use_attested")
    if not attested:
        raise ApiError(ERR_INVALID_REQUEST, "aeronautical_use_attested must be true at lease signing", 400)
    sublease_allowed = req_bool(data, "sublease_allowed")
    policy_number = req_str(data, "insurance_policy_number")
    insurer_name = req_str(data, "insurance_insurer_name")
    coverage = req_int(data, "insurance_liability_coverage_cents")
    ins_from = req_dt(data, "insurance_effective_from")
    ins_to = req_dt(data, "insurance_effective_to")
    aircraft_n_number = req_str(data, "aircraft_n_number")
    aircraft_make_model = req_str(data, "aircraft_make_model")

    if coverage < MIN_LIABILITY_COVERAGE_CENTS or not (ins_from <= now < ins_to):
        raise ApiError(ERR_INSUFFICIENT_COVERAGE, "Insurance coverage does not satisfy the minimum or does not cover the current instant", 422)
    if n_number_in_use(offer["airport_id"], aircraft_n_number):
        raise ApiError(ERR_DUPLICATE_N_NUMBER, "n_number already BASED on another active-phase lease at this airport", 422)

    app = db.applications[offer["application_id"]]

    # --- atomic commit -------------------------------------------------------
    offer["status"] = "ACCEPTED"
    touch(offer)
    lease = db.new_entity({
        "airport_id": offer["airport_id"],
        "hangar_id": hangar["id"],
        "application_id": app["id"],
        "offer_id": offer["id"],
        "tenant_name": app["applicant_name"],
        "base_monthly_rate_cents": offer["quoted_monthly_rate_cents"],
        "current_monthly_rate_cents": offer["quoted_monthly_rate_cents"],
        "lease_start_date": iso_z(now),
        "last_escalation_anniversary": 0,
        "aeronautical_use_attested": True,
        "sublease_allowed": sublease_allowed,
        "days_delinquent": 0,
        "outstanding_balance_cents": 0,
        "status": "ACTIVE",
    })
    db.leases[lease["id"]] = lease
    create_first_charge(lease)

    cert = db.new_entity({
        "lease_id": lease["id"],
        "insurer_name": insurer_name,
        "policy_number": policy_number,
        "liability_coverage_cents": coverage,
        "effective_from": iso_z(ins_from),
        "effective_to": iso_z(ins_to),
        "status": "VALID",
    })
    db.certificates[cert["id"]] = cert

    aircraft = db.new_entity({
        "lease_id": lease["id"],
        "n_number": aircraft_n_number,
        "make_model": aircraft_make_model,
        "is_primary": True,
        "removed_at": None,
        "status": "BASED",
    })
    db.aircraft[aircraft["id"]] = aircraft

    # ACCEPTED -> LEASED is an atomic continuation within this same request.
    app["status"] = "LEASED"
    touch(app)
    # Posture flips to LEASED; hangar version increments by exactly one (OCC).
    touch(hangar)
    return success_obj(db.public(lease), 201)


@bp.post("/offers/<oid>/decline")
def decline_offer(oid):
    uid, _role = require_roles("Applicant")
    offer = get_offer_or_404(oid)
    require_ownership(offer["application_id"], uid)
    if offer["status"] != "OPEN":
        raise ApiError(ERR_OFFER_NOT_OPEN, "Offer must be OPEN to decline", 409)
    app = db.applications[offer["application_id"]]
    prior = app["decline_count"]
    app["decline_count"] = prior + 1
    # One free decline per application lifetime: the first returns to QUEUED;
    # a decline with decline_count >= 1 already on record moves to REJECTED
    # (it does not error).
    app["status"] = "QUEUED" if prior == 0 else "REJECTED"
    touch(app)
    offer["status"] = "DECLINED"
    touch(offer)
    return success_obj(db.public(offer), 200)
