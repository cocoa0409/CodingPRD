"""Voyage endpoints (PRD section 3.5).

Voyage etd must lie inside the carrier contract's CLOSED service window;
isf_deadline = etd - 24h and ams_deadline = etd - 48h are derived at creation.
Departure and blank sailings cascade through bookings, bills of lading,
invoices, assignments, and consolidations.
"""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_CONTRACT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_VOYAGE_HAS_OPEN_BOOKINGS,
    ERR_VOYAGE_INVALID_STATE,
    ERR_VOYAGE_NOT_ARRIVABLE,
    ERR_VOYAGE_NOT_DEPARTABLE,
    ERR_VOYAGE_NOT_FOUND,
    ERR_VOYAGE_OUTSIDE_CONTRACT_WINDOW,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import domain
from util import (
    apply_filters,
    get_json_body,
    has_field,
    paginate,
    parse_pagination,
    pub,
    require_string,
    require_ts,
    sort_by_created_at,
)

bp = Blueprint("voyages", __name__)


def _get_voyage(voyage_id: str) -> dict:
    voyage = db.voyages.get(voyage_id)
    if voyage is None:
        raise_err(ERR_VOYAGE_NOT_FOUND, "Voyage id does not exist")
    return voyage


@bp.route("/freight/voyages", methods=["POST"])
@require_roles("OperationsManager")
def create_voyage(_user_id: str, _role: str):
    body = get_json_body()

    # Band 3: FK existence for a present carrier_contract_id.
    contract = None
    if has_field(body, "carrier_contract_id"):
        contract = db.carrier_contracts.get(body["carrier_contract_id"])
        if contract is None:
            raise_err(ERR_CONTRACT_NOT_FOUND, "carrier_contract_id does not exist")

    # Band 5: body shape.
    vessel_name = require_string(body, "vessel_name")
    voyage_number = require_string(body, "voyage_number")
    require_string(body, "carrier_contract_id")
    origin_port = require_string(body, "origin_port")
    destination_port = require_string(body, "destination_port")
    etd = require_ts(body, "etd")
    eta = require_ts(body, "eta")
    if not (eta > etd):
        raise_err(ERR_INVALID_REQUEST, "eta must be strictly later than etd")

    # Band 6: contract must be ACTIVE (lazy expiry evaluated on use).
    domain.lazy_expire_contract(contract)
    if contract["status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_NOT_ACTIVE, "Carrier contract must be ACTIVE for voyage creation")

    # Band 11: etd inside the contract's CLOSED [service_start, service_end].
    if not (db.parse_iso(contract["service_start"]) <= etd <= db.parse_iso(contract["service_end"])):
        raise_err(
            ERR_VOYAGE_OUTSIDE_CONTRACT_WINDOW,
            "Voyage etd is outside the contract's closed service window",
        )

    voyage = {
        "vessel_name": vessel_name,
        "voyage_number": voyage_number,
        "carrier_contract_id": contract["id"],
        "origin_port": origin_port,
        "destination_port": destination_port,
        "etd": db.format_iso(etd),
        "eta": db.format_iso(eta),
        "isf_deadline": db.format_iso(etd - timedelta(hours=24)),
        "ams_deadline": db.format_iso(etd - timedelta(hours=48)),
        "status": "SCHEDULED",
    }
    db.stamp_new(voyage)
    db.voyages[voyage["id"]] = voyage
    return success_object(pub(voyage), 201)


@bp.route("/freight/voyages", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_voyages(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.voyages.values()))
    items = apply_filters(items, ["status", "carrier_contract_id"])
    page, total = paginate(items, limit, offset)
    return success_list([pub(v) for v in page], limit, offset, total)


@bp.route("/freight/voyages/<voyage_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_voyage(voyage_id: str, _user_id: str, _role: str):
    return success_object(pub(_get_voyage(voyage_id)))


@bp.route("/freight/voyages/<voyage_id>/open-for-booking", methods=["POST"])
@require_roles("OperationsManager")
def open_for_booking(voyage_id: str, _user_id: str, _role: str):
    voyage = _get_voyage(voyage_id)
    if voyage["status"] != "SCHEDULED":
        raise_err(ERR_VOYAGE_INVALID_STATE, "Voyage must be SCHEDULED to open for booking")
    voyage["status"] = "BOOKING_OPEN"
    db.touch(voyage)
    return success_object(pub(voyage))


@bp.route("/freight/voyages/<voyage_id>/depart", methods=["POST"])
@require_roles("OperationsManager")
def depart_voyage(voyage_id: str, _user_id: str, _role: str):
    voyage = _get_voyage(voyage_id)
    if voyage["status"] != "BOOKING_OPEN":
        raise_err(ERR_VOYAGE_INVALID_STATE, "Voyage must be BOOKING_OPEN to depart")
    if db.clock() < db.parse_iso(voyage["etd"]):
        raise_err(ERR_VOYAGE_NOT_DEPARTABLE, "Logical clock is before the voyage etd")
    voyage["status"] = "DEPARTED"
    db.touch(voyage)
    domain.voyage_depart_cascade(voyage)
    return success_object(pub(voyage))


@bp.route("/freight/voyages/<voyage_id>/arrive", methods=["POST"])
@require_roles("OperationsManager")
def arrive_voyage(voyage_id: str, _user_id: str, _role: str):
    voyage = _get_voyage(voyage_id)
    if voyage["status"] != "DEPARTED":
        raise_err(ERR_VOYAGE_INVALID_STATE, "Voyage must be DEPARTED to arrive")
    if db.clock() < db.parse_iso(voyage["eta"]):
        raise_err(ERR_VOYAGE_NOT_ARRIVABLE, "Logical clock is before the voyage eta")
    voyage["status"] = "ARRIVED"
    db.touch(voyage)
    domain.voyage_arrive_cascade(voyage)
    return success_object(pub(voyage))


@bp.route("/freight/voyages/<voyage_id>/close", methods=["POST"])
@require_roles("OperationsManager")
def close_voyage(voyage_id: str, _user_id: str, _role: str):
    voyage = _get_voyage(voyage_id)
    if voyage["status"] != "ARRIVED":
        raise_err(ERR_VOYAGE_INVALID_STATE, "Voyage must be ARRIVED to close")
    open_bookings = [
        b
        for b in db.bookings.values()
        if b["voyage_id"] == voyage["id"] and b["status"] not in ("DELIVERED", "CANCELLED")
    ]
    if open_bookings:
        raise_err(ERR_VOYAGE_HAS_OPEN_BOOKINGS, "Every booking must be DELIVERED or CANCELLED to close")
    voyage["status"] = "CLOSED"
    db.touch(voyage)
    return success_object(pub(voyage))


@bp.route("/freight/voyages/<voyage_id>/blank", methods=["POST"])
@require_roles("OperationsManager")
def blank_voyage(voyage_id: str, _user_id: str, _role: str):
    voyage = _get_voyage(voyage_id)
    if voyage["status"] not in ("SCHEDULED", "BOOKING_OPEN"):
        raise_err(ERR_VOYAGE_INVALID_STATE, "Voyage must be SCHEDULED or BOOKING_OPEN to blank")
    voyage["status"] = "BLANKED"
    db.touch(voyage)
    domain.voyage_blank_cascade(voyage)
    return success_object(pub(voyage))
