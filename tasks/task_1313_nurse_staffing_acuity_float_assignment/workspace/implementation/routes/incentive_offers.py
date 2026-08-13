"""IncentiveOffer endpoints: premium offers with budget reservation, claim,
withdrawal, and settlement hooks."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_SHIFT_NOT_FOUND,
    ERR_NURSE_NOT_FOUND,
    ERR_OFFER_NOT_FOUND,
    ERR_OFFER_INVALID_STATE,
    ERR_SHIFT_ADEQUATELY_STAFFED,
    ERR_OFFER_ALREADY_ACTIVE,
    ERR_INCENTIVE_BUDGET_EXCEEDED,
    ERR_COMPETENCY_NOT_HELD,
    ERR_SHIFT_OVERLAP,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.core import (
    create_assignment,
    create_offer,
    offered_offer_for_shift,
    premium_reserve,
    incentive_reserved_cents,
    nurse_has_overlap,
    refresh_shift_and_touch,
    pub,
)
from util import get_json_body, req_num, opt_int, parse_pagination, paginate, apply_filters

bp = Blueprint("incentive_offers", __name__)


@bp.post("/incentive-offers")
@require_roles("NurseAdmin")
def create_incentive_offer(_user_id: str, _role: str):
    body = get_json_body()

    # Body FK: presence, then existence.
    if "shift_id" not in body or body["shift_id"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: shift_id")
    shift_id = body["shift_id"]
    if not isinstance(shift_id, str) or shift_id == "":
        raise_err(ERR_INVALID_REQUEST, "shift_id must be a string")
    shift = db.shifts.get(shift_id)
    if shift is None:
        raise_err(ERR_SHIFT_NOT_FOUND, "Shift not found")

    premium_multiplier = req_num(body, "premium_multiplier")
    if not (premium_multiplier > 1.0 and premium_multiplier <= 3.0):
        raise_err(ERR_INVALID_REQUEST, "premium_multiplier must be > 1.0 and <= 3.0")
    flat_bonus_cents = opt_int(body, "flat_bonus_cents", 0)
    if flat_bonus_cents < 0:
        raise_err(ERR_INVALID_REQUEST, "flat_bonus_cents must be >= 0")

    # Business safety (tier 7): offers are lawful only while the shift is short.
    if shift["staffing_posture"] == "ADEQUATE":
        raise_err(ERR_SHIFT_ADEQUATELY_STAFFED,
                  "Incentive offers require an UNDERSTAFFED or CRITICAL posture")

    # Uniqueness (tier 8): at most one OFFERED offer per shift.
    if offered_offer_for_shift(shift["id"]) is not None:
        raise_err(ERR_OFFER_ALREADY_ACTIVE, "An OFFERED incentive offer already exists for the shift")

    # Fiscal gate (tier 10): reserve must fit the unit budget.
    unit = db.units[shift["unit_id"]]
    reserve = premium_reserve(premium_multiplier, flat_bonus_cents)
    if incentive_reserved_cents(unit["id"]) + reserve > unit["incentive_budget_cents"]:
        raise_err(ERR_INCENTIVE_BUDGET_EXCEEDED,
                  "premium_reserve_cents would exceed the unit's remaining incentive budget")

    offer = create_offer(shift, premium_multiplier, flat_bonus_cents, origin="MANUAL")
    return success_object(pub(offer), 201)


@bp.get("/incentive-offers")
@require_roles(*ALL_ROLES)
def list_incentive_offers(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sorted(db.offers.values(), key=lambda o: o["created_at"])
    items = apply_filters(items, {
        "shift_id": request.args.get("shift_id"),
        "claimed_nurse_id": request.args.get("claimed_nurse_id"),
        "claimed_assignment_id": request.args.get("claimed_assignment_id"),
        "status": request.args.get("status"),
    })
    page, total = paginate(items, limit, offset)
    return success_list([pub(o) for o in page], limit, offset, total)


@bp.get("/incentive-offers/<offerId>")
@require_roles(*ALL_ROLES)
def get_incentive_offer(offerId: str, _user_id: str, _role: str):
    offer = db.offers.get(offerId)
    if offer is None:
        raise_err(ERR_OFFER_NOT_FOUND, "Incentive offer not found")
    return success_object(pub(offer))


@bp.post("/incentive-offers/<offerId>/claim")
@require_roles("StaffNurse")
def claim_incentive_offer(offerId: str, _user_id: str, _role: str):
    offer = db.offers.get(offerId)
    if offer is None:
        raise_err(ERR_OFFER_NOT_FOUND, "Incentive offer not found")
    if offer["status"] != "OFFERED":
        raise_err(ERR_OFFER_INVALID_STATE, "claim requires an OFFERED offer")

    nurse = db.nurses.get(_user_id)
    if nurse is None:
        raise_err(ERR_NURSE_NOT_FOUND, "Acting nurse not found")

    shift = db.shifts[offer["shift_id"]]
    unit = db.units[shift["unit_id"]]
    if unit["unit_type"] not in nurse["competencies"]:
        raise_err(ERR_COMPETENCY_NOT_HELD, "Nurse's competencies do not include the shift's unit_type")
    if nurse_has_overlap(nurse["id"], shift["_start_dt"], shift["_end_dt"]):
        raise_err(ERR_SHIFT_OVERLAP, "Claim would overlap an existing live commitment")

    assignment = create_assignment(
        shift,
        nurse,
        source="INCENTIVE",
        status="ACCEPTED",
        premium_multiplier=offer["premium_multiplier"],
        flat_bonus_cents=offer["flat_bonus_cents"],
    )
    offer["status"] = "CLAIMED"
    offer["claimed_nurse_id"] = nurse["id"]
    offer["claimed_assignment_id"] = assignment["id"]
    db.touch(offer)
    refresh_shift_and_touch(shift)
    return success_object(pub(offer), 200)


@bp.post("/incentive-offers/<offerId>/withdraw")
@require_roles("NurseAdmin")
def withdraw_incentive_offer(offerId: str, _user_id: str, _role: str):
    offer = db.offers.get(offerId)
    if offer is None:
        raise_err(ERR_OFFER_NOT_FOUND, "Incentive offer not found")
    if offer["status"] != "OFFERED":
        raise_err(ERR_OFFER_INVALID_STATE, "withdraw requires an OFFERED offer")
    offer["status"] = "WITHDRAWN"  # reserve released
    db.touch(offer)
    return success_object(pub(offer), 200)
