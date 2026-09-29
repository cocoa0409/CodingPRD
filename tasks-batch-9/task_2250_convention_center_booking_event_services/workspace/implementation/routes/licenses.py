"""The license agreement and the road to DEFINITE (PRD 3.4)."""

from flask import Blueprint

import calc
import clock
import lookups
import validate
from db import db
from errors import err
from middleware import body, endpoint, filter_rows, require_owner, touch
from response import entity_response
from routes.common import listing
from services import engine
from util import iso_instant

bp = Blueprint("licenses", __name__)

LIVE_LICENSE_STATES = ("DRAFT", "ISSUED", "EXECUTED", "AMENDMENT_PENDING")
AMENDABLE_BOOKING_STATES = ("TENTATIVE", "DEFINITE", "IN_HOUSE")


@bp.post("/bookings/<booking_id>/license")
@endpoint("SalesManager")
def draft_license(booking_id):
    booking = lookups.fetch("booking", booking_id)
    for existing in lookups.licenses_of_booking(booking["id"]):
        if existing["status"] in LIVE_LICENSE_STATES:
            raise err("ERR_LICENSE_ALREADY_EXISTS")
    space = db.spaces.get(booking["space_id"])
    lic = db.insert(
        "license",
        {
            "booking_id": booking["id"],
            "status": "DRAFT",
            "rental_rate_cents": space["daily_base_rate_cents"] if space else 0,
            "contracted_rental_cents": booking["contracted_rental_cents"],
            "deposit_required_cents": booking["deposit_required_cents"],
            "deposit_held_cents": 0,
            "amendment_round": 0,
            "pending_amendment_note": None,
            "issued_at_utc": None,
            "executed_at_utc": None,
        },
    )
    return entity_response(lic, 201)


@bp.get("/licenses")
@endpoint("VenueAdmin", "SalesManager", "SettlementAnalyst", "Licensee")
def list_licenses():
    return listing(filter_rows("license", {"booking_id": "booking_id", "status": "status"}))


@bp.get("/licenses/<license_id>")
@endpoint("VenueAdmin", "SalesManager", "SettlementAnalyst", "Licensee")
def read_license(license_id):
    return entity_response(lookups.fetch("license", license_id))


@bp.post("/licenses/<license_id>/issue")
@endpoint("SalesManager")
def issue_license(license_id):
    lic = lookups.fetch("license", license_id)
    if lic["status"] != "DRAFT":
        raise err("ERR_LICENSE_STATE_INVALID")
    booking = db.bookings.get(lic["booking_id"])
    if booking is None or booking["status"] != "TENTATIVE":
        raise err("ERR_BOOKING_STATE_INVALID")
    client = db.clients.get(booking["client_id"])
    required = lic["deposit_required_cents"]
    if client is None or client["credit_balance_cents"] < required:
        raise err("ERR_INSUFFICIENT_DEPOSIT_CREDIT")

    client["credit_balance_cents"] = client["credit_balance_cents"] - required
    touch(client)
    lic["status"] = "ISSUED"
    lic["deposit_held_cents"] = required
    lic["issued_at_utc"] = iso_instant(clock.now())
    touch(lic)
    return entity_response(lic)


@bp.post("/licenses/<license_id>/countersign")
@endpoint("Licensee")
def countersign_license(license_id):
    lic = lookups.fetch("license", license_id)
    booking = db.bookings.get(lic["booking_id"])
    require_owner(booking["client_id"] if booking else None)
    if lic["status"] != "ISSUED":
        raise err("ERR_LICENSE_STATE_INVALID")

    lic["status"] = "EXECUTED"
    if lic.get("executed_at_utc") is None:
        lic["executed_at_utc"] = iso_instant(clock.now())
    touch(lic)
    return entity_response(lic)


@bp.post("/licenses/<license_id>/amendments")
@endpoint("SalesManager")
def open_amendment(license_id):
    lic = lookups.fetch("license", license_id)
    payload = body()
    expected = validate.req_int(payload, "expected_license_version")
    note = validate.req_string(payload, "amendment_note")

    if lic["status"] != "EXECUTED":
        raise err("ERR_LICENSE_STATE_INVALID")
    booking = db.bookings.get(lic["booking_id"])
    if booking is None or booking["status"] not in AMENDABLE_BOOKING_STATES:
        raise err("ERR_BOOKING_STATE_INVALID")
    if expected != lic["version"]:
        raise err("ERR_STALE_LICENSE_VERSION")
    if lic["amendment_round"] >= calc.MAX_AMENDMENT_ROUNDS:
        raise err("ERR_AMENDMENT_LIMIT_REACHED")

    lic["status"] = "AMENDMENT_PENDING"
    lic["pending_amendment_note"] = note
    touch(lic)
    return entity_response(lic)


@bp.post("/licenses/<license_id>/accept-amendment")
@endpoint("Licensee")
def accept_amendment(license_id):
    lic = lookups.fetch("license", license_id)
    booking = db.bookings.get(lic["booking_id"])
    require_owner(booking["client_id"] if booking else None)
    if lic["status"] != "AMENDMENT_PENDING":
        raise err("ERR_LICENSE_STATE_INVALID")

    lic["status"] = "EXECUTED"
    lic["amendment_round"] = lic["amendment_round"] + 1
    lic["pending_amendment_note"] = None
    touch(lic)
    return entity_response(lic)


@bp.post("/licenses/<license_id>/terminate")
@endpoint("VenueAdmin")
def terminate_license(license_id):
    lic = lookups.fetch("license", license_id)
    if lic["status"] != "EXECUTED":
        raise err("ERR_LICENSE_STATE_INVALID")
    booking = db.bookings.get(lic["booking_id"])
    if booking is None or booking["status"] not in ("TENTATIVE", "DEFINITE"):
        raise err("ERR_BOOKING_STATE_INVALID")
    if lookups.settlements_of_booking(booking["id"]):
        raise err("ERR_SETTLEMENT_ALREADY_EXISTS")

    held = lic.get("deposit_held_cents") or 0
    if held:
        client = db.clients.get(booking["client_id"])
        if client is not None:
            client["credit_balance_cents"] = client["credit_balance_cents"] + held
            touch(client)
        lic["deposit_held_cents"] = 0
    lic["status"] = "TERMINATED"
    touch(lic)

    engine.release_booking(booking)
    return entity_response(lic)
