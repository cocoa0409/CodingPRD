"""PenaltyCharge endpoints (PRD §3.8)."""
from flask import Blueprint, request

from constants import ROLE_STUDIO_MANAGER, ROLE_MEMBER
from db import db, touch
from errors import err, ERR_OWNERSHIP_VIOLATION, ERR_INVALID_STATE
from middleware import require_auth, require_role
from response import success_object, success_array
from serializers import penalty_out
from services import lookup, paging
from services import members as member_svc

bp = Blueprint("penalties", __name__)

READ_ROLES = {ROLE_STUDIO_MANAGER, ROLE_MEMBER}


@bp.route("/penalty-charges/<charge_id>", methods=["GET"])
def get_penalty(charge_id):
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    rec = lookup.get_penalty(charge_id)
    if role == ROLE_MEMBER and user_id != rec["member_id"]:
        raise err(ERR_OWNERSHIP_VIOLATION, "Members may only read their own penalty charges")
    return success_object(penalty_out(rec), 200)


@bp.route("/penalty-charges", methods=["GET"])
def list_penalties():
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    limit, offset = paging.get_pagination()
    f_member = request.args.get("member_id")
    f_reservation = request.args.get("reservation_id")
    records = []
    for p in db.penalty_charges.values():
        if f_member is not None and p["member_id"] != f_member:
            continue
        if f_reservation is not None and p["reservation_id"] != f_reservation:
            continue
        if role == ROLE_MEMBER and p["member_id"] != user_id:
            continue
        records.append(p)
    records = paging.sort_default(records)
    page, total = paging.apply_page(records, limit, offset)
    return success_array([penalty_out(p) for p in page], limit, offset, total)


@bp.route("/penalty-charges/<charge_id>/waive", methods=["POST"])
def waive_penalty(charge_id):
    _, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER})
    rec = lookup.get_penalty(charge_id)
    if rec["waived"]:
        raise err(ERR_INVALID_STATE, "Penalty charge is already waived")
    rec["waived"] = True
    touch(rec)
    member = db.members.get(rec["member_id"])
    if member is not None:
        # credit wallet by amount; recompute strikes (waived no longer counts).
        member["wallet_credit_cents"] += rec["amount_cents"]
        touch(member)
        # Recompute is implicit via active_strike_count at read time. Waiver does
        # NOT auto-reinstate a suspended member (PRD §3.8).
    return success_object(penalty_out(rec), 200)
