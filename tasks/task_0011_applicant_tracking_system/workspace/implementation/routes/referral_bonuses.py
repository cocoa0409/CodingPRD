"""ReferralBonus endpoints."""
from flask import Blueprint, request

import db
from auth import require_role
from common import (
    parse_pagination,
    paginate,
    get_or_404,
    stamp_update,
)
from errors import ApiError, ERR_INVALID_STATE
from response import success_object, success_array
from serializers import ser_referral_bonus


bp = Blueprint("referral_bonuses", __name__)


@bp.get("/ats/referral-bonuses/<rb_id>")
def read_referral_bonus(rb_id):
    require_role({"PayrollOfficer", "HiringManager", "PlatformAdmin"})
    rb = get_or_404(db.referral_bonuses, rb_id, "referral bonus")
    return success_object(ser_referral_bonus(rb), status=200)


@bp.get("/ats/referral-bonuses")
def list_referral_bonuses():
    require_role({"PayrollOfficer", "HiringManager", "PlatformAdmin"})
    limit, offset = parse_pagination()
    rows = list(db.referral_bonuses.values())
    referrer_f = request.args.get("referrer_user_id")
    cand_f = request.args.get("candidate_id")
    offer_f = request.args.get("offer_id")
    status_f = request.args.get("status")
    if referrer_f:
        rows = [r for r in rows if r["referrer_user_id"] == referrer_f]
    if cand_f:
        rows = [r for r in rows if r["candidate_id"] == cand_f]
    if offer_f:
        rows = [r for r in rows if r["offer_id"] == offer_f]
    if status_f:
        rows = [r for r in rows if r["status"] == status_f]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return success_array([ser_referral_bonus(r) for r in page], limit, offset, total, status=200)


@bp.post("/ats/referral-bonuses/<rb_id>/pay")
def pay_referral_bonus(rb_id):
    require_role({"PayrollOfficer"})
    rb = get_or_404(db.referral_bonuses, rb_id, "referral bonus")
    if rb["status"] != "PAYABLE":
        raise ApiError(ERR_INVALID_STATE, 409, "referral bonus not in PAYABLE")
    rb["status"] = "PAID"
    stamp_update(rb)
    return success_object(ser_referral_bonus(rb), status=200)


@bp.post("/ats/referral-bonuses/<rb_id>/void")
def void_referral_bonus(rb_id):
    require_role({"PayrollOfficer"})
    rb = get_or_404(db.referral_bonuses, rb_id, "referral bonus")
    if rb["status"] != "PAYABLE":
        raise ApiError(ERR_INVALID_STATE, 409, "referral bonus not in PAYABLE")
    rb["status"] = "VOID"
    stamp_update(rb)
    return success_object(ser_referral_bonus(rb), status=200)
