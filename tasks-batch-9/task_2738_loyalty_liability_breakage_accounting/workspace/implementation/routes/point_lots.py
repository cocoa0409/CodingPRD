"""PointLot endpoints and the lot-side allocation ledger read (PRD §3.3)."""
from flask import Blueprint

import calc
import db
import lookup
import serialize
from auth import (ROLE_CONTROLLER, ROLE_LOYALTY_ACCOUNTANT, ROLE_MEMBER,
                  ROLE_PROGRAM_ADMIN, authorize, require_member_owns)
from errors import ApiError
from response import created, ok, paginate
from util import add_days, clock
from validate import field_int, field_ref, json_body

bp = Blueprint("point_lots", __name__)

READ_ROLES = (ROLE_PROGRAM_ADMIN, ROLE_LOYALTY_ACCOUNTANT, ROLE_CONTROLLER)


@bp.route("/point-lots", methods=["POST"])
def create_point_lot():
    authorize(ROLE_LOYALTY_ACCOUNTANT)
    body = json_body()
    member_id = field_ref(body, "member_id")
    period_id = field_ref(body, "period_id")
    agreement_id = field_ref(body, "partner_agreement_id", required=False)
    base_points = field_int(body, "base_points", minimum=1)
    promo_multiplier_bp = field_int(body, "promo_multiplier_bp", required=False,
                                   default=10000, minimum=10000)
    member = lookup.member(member_id)
    period = lookup.period(period_id)
    agreement = lookup.partner_agreement(agreement_id) if agreement_id else None
    if period["state"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN", 409)
    program = lookup.program(member["program_id"])
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409)
    if period["program_id"] != member["program_id"]:
        raise ApiError("ERR_PERIOD_PROGRAM_MISMATCH", 409)
    if agreement is not None and agreement["program_id"] != member["program_id"]:
        raise ApiError("ERR_AGREEMENT_PROGRAM_MISMATCH", 409)
    if promo_multiplier_bp > program["promo_multiplier_cap_bp"]:
        raise ApiError("ERR_PROMO_MULTIPLIER_ABOVE_CAP", 409)
    tier_multiplier = program["tier_multiplier_bp"].get(member["tier"], 10000)
    ssp = program["ssp_millicents_per_point"]
    rate = program["current_breakage_rate_bp"]
    figures = calc.issuance_measurement(base_points, promo_multiplier_bp,
                                        tier_multiplier, ssp, rate)
    if figures["points_issued"] > program["per_issuance_point_cap"]:
        raise ApiError("ERR_ISSUANCE_CAP_EXCEEDED", 409)
    issued_at = clock.now()
    fields = {
        "member_id": member_id,
        "period_id": period_id,
        "partner_agreement_id": agreement_id if agreement_id else None,
        "base_points": base_points,
        "promo_multiplier_bp": promo_multiplier_bp,
        "tier_multiplier_bp_at_issue": tier_multiplier,
        "ssp_millicents_per_point_at_issue": ssp,
        "breakage_rate_bp_at_issue": rate,
        "expired_gross_ssp_cents": 0,
        "escheated_cents": 0,
        "issued_at": issued_at,
        "expires_at": add_days(issued_at, program["point_expiry_days"]),
        "lifecycle_state": "OUTSTANDING",
        "settlement_state": "PENDING_SETTLEMENT" if agreement else "NOT_APPLICABLE",
    }
    fields.update(figures)
    rec = db.new_record(db.store.point_lots, fields)
    period["issuance_deferred_cents"] = (
        period["issuance_deferred_cents"] + rec["deferred_revenue_cents"]
    )
    member["last_activity_at"] = issued_at
    if member["status"] == "DORMANT":
        member["status"] = "ACTIVE"
        db.touch(member)
    if agreement is not None:
        db.touch(agreement)
    return created(serialize.point_lot(rec))


@bp.route("/point-lots", methods=["GET"])
def list_point_lots():
    authorize(*READ_ROLES)
    rows = lookup.filtered(db.rows(db.store.point_lots), "member_id", "period_id",
                           "partner_agreement_id", "lifecycle_state",
                           "settlement_state")
    return paginate(rows, serialize.point_lot)


@bp.route("/point-lots/<lot_id>", methods=["GET"])
def read_point_lot(lot_id):
    user_id, role = authorize(*READ_ROLES, ROLE_MEMBER)
    lot = lookup.point_lot(lot_id)
    require_member_owns(user_id, role, lot["member_id"])
    return ok(serialize.point_lot(lot))


@bp.route("/point-lots/<lot_id>/allocations", methods=["GET"])
def list_lot_allocations(lot_id):
    authorize(*READ_ROLES)
    lot = lookup.point_lot(lot_id)
    rows = [a for a in db.store.allocations.values()
            if a["point_lot_id"] == lot["id"]]
    rows = lookup.filtered(rows, "entry_type")
    return paginate(db.allocation_order(rows), serialize.allocation)
