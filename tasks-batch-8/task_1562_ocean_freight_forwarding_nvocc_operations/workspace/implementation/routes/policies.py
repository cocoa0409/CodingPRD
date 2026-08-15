"""Cargo insurance policy endpoints (PRD section 3.13).

Quote computes, in pinned order, chargeable weight -> freight base (ocean
freight line only) -> insured value (CIF + 10%) -> premium (coverage rate with
a minimum premium floor). Binding makes the premium billable on the booking's
next FREIGHT invoice.
"""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_BOOKING_INVALID_STATE,
    ERR_BOOKING_NOT_FOUND,
    ERR_CLAIMS_OPEN,
    ERR_POLICY_INVALID_STATE,
    ERR_POLICY_NOT_FOUND,
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
    require_enum,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("insurance_policies", __name__)

COVERAGE_TYPES = {"ALL_RISK", "WA", "FPA"}
POLICY_BOOKING_STATES = {"CONFIRMED", "DOCUMENTATION_CLEARED", "LOADED"}


def _get_policy(policy_id: str) -> dict:
    pol = db.insurance_policies.get(policy_id)
    if pol is None:
        raise_err(ERR_POLICY_NOT_FOUND, "CargoInsurancePolicy id does not exist")
    return pol


@bp.route("/freight/insurance-policies", methods=["POST"])
@require_roles("BookingCoordinator")
def create_policy(_user_id: str, _role: str):
    body = get_json_body()

    # Band 3: booking FK existence.
    booking = None
    if has_field(body, "booking_id"):
        booking = db.bookings.get(body["booking_id"])
        if booking is None:
            raise_err(ERR_BOOKING_NOT_FOUND, "booking_id does not exist")

    # Band 5: body shape.
    require_string(body, "booking_id")
    coverage_type = require_enum(body, "coverage_type", COVERAGE_TYPES)
    cargo_value_cents = require_int(body, "cargo_value_cents", minimum=1)

    # Band 6: booking state permits quoting.
    if booking["status"] not in POLICY_BOOKING_STATES:
        raise_err(ERR_BOOKING_INVALID_STATE, "Booking state does not permit insurance quoting")

    # Pinned evaluation order: chargeable weight -> freight BASE (no BAF/THC/
    # DOC/rollover) -> insured (CIF + 10%) -> premium (rate, floor).
    freight_base_cents = booking["_freight"]["base_cents"]
    insured, premium = domain.compute_insured_and_premium(
        coverage_type, cargo_value_cents, freight_base_cents
    )

    pol = {
        "booking_id": booking["id"],
        "policy_number": f"POL-{db.next_seq('policy')}",
        "coverage_type": coverage_type,
        "cargo_value_cents": cargo_value_cents,
        "insured_value_cents": insured,
        "freight_base_cents": freight_base_cents,
        "premium_cents": premium,
        "status": "QUOTED",
    }
    db.stamp_new(pol)
    db.insurance_policies[pol["id"]] = pol
    return success_object(pub(pol), 201)


@bp.route("/freight/insurance-policies", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_policies(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.insurance_policies.values()))
    items = apply_filters(items, ["booking_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list([pub(p) for p in page], limit, offset, total)


@bp.route("/freight/insurance-policies/<policy_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_policy(policy_id: str, _user_id: str, _role: str):
    return success_object(pub(_get_policy(policy_id)))


@bp.route("/freight/insurance-policies/<policy_id>/bind", methods=["POST"])
@require_roles("BookingCoordinator")
def bind_policy(policy_id: str, _user_id: str, _role: str):
    pol = _get_policy(policy_id)
    get_json_body()
    if pol["status"] != "QUOTED":
        raise_err(ERR_POLICY_INVALID_STATE, "Policy must be QUOTED to bind")
    booking = db.bookings.get(pol["booking_id"])
    if booking is None or booking["status"] not in POLICY_BOOKING_STATES:
        raise_err(ERR_BOOKING_INVALID_STATE, "Booking state does not permit binding")
    pol["status"] = "BOUND"
    db.touch(pol)
    return success_object(pub(pol))


@bp.route("/freight/insurance-policies/<policy_id>/cancel", methods=["POST"])
@require_roles("BookingCoordinator")
def cancel_policy(policy_id: str, _user_id: str, _role: str):
    pol = _get_policy(policy_id)
    get_json_body()
    if pol["status"] not in ("QUOTED", "BOUND"):
        raise_err(ERR_POLICY_INVALID_STATE, "Policy must be QUOTED or BOUND to cancel")
    for cl in db.cargo_claims.values():
        if cl["policy_id"] == pol["id"] and cl["status"] in ("FILED", "UNDER_REVIEW", "APPROVED"):
            raise_err(ERR_CLAIMS_OPEN, "Policy has an open claim")
    pol["status"] = "CANCELLED"
    db.touch(pol)
    return success_object(pub(pol))
