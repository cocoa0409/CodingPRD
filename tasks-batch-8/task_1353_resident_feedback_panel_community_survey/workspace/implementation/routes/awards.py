from flask import Blueprint, request

from core import (ApiError, db, list_response, ok, require_roles, touch)
from serializers import ser_award

bp = Blueprint("awards", __name__)


def get_award_or_404(award_id):
    a = db.awards.get(award_id)
    if a is None:
        raise ApiError("ERR_AWARD_NOT_FOUND", 404, "Incentive award not found")
    return a


@bp.get("/feedback-panel/incentive-awards")
@require_roles("IncentiveClerk", "PanelManager")
def list_awards():
    items = list(db.awards.values())
    response_id = request.args.get("response_id")
    if response_id is not None:
        items = [a for a in items if a["response_id"] == response_id]
    wave_id = request.args.get("wave_id")
    if wave_id is not None:
        items = [a for a in items if a["wave_id"] == wave_id]
    payout_status = request.args.get("payout_status")
    if payout_status is not None:
        items = [a for a in items if a["payout_status"] == payout_status]
    eligibility_status = request.args.get("eligibility_status")
    if eligibility_status is not None:
        items = [a for a in items if a["eligibility_status"] == eligibility_status]
    return list_response(items, ser_award)


@bp.get("/feedback-panel/incentive-awards/<award_id>")
@require_roles("IncentiveClerk")
def get_award(award_id):
    return ok(ser_award(get_award_or_404(award_id)))


@bp.post("/feedback-panel/incentive-awards/<award_id>/authorize")
@require_roles("IncentiveClerk")
def authorize(award_id):
    a = get_award_or_404(award_id)
    if a["eligibility_status"] != "ELIGIBLE" or a["payout_status"] != "UNPAID":
        raise ApiError("ERR_AWARD_NOT_AUTHORIZED_STATE", 409,
                       "Authorize requires eligibility ELIGIBLE and payout UNPAID")
    wave = db.waves[a["wave_id"]]
    if wave["incentive_pool_available_cents"] < a["amount_cents"]:
        raise ApiError("ERR_INCENTIVE_POOL_INSUFFICIENT", 402,
                       "Wave incentive pool cannot cover the award amount")
    wave["incentive_pool_available_cents"] -= a["amount_cents"]
    wave["incentive_pool_reserved_cents"] += a["amount_cents"]
    touch(wave)
    a["payout_status"] = "AUTHORIZED"
    touch(a)
    return ok(ser_award(a))


@bp.post("/feedback-panel/incentive-awards/<award_id>/pay")
@require_roles("IncentiveClerk")
def pay(award_id):
    a = get_award_or_404(award_id)
    if a["payout_status"] != "AUTHORIZED":
        raise ApiError("ERR_AWARD_NOT_PAID_STATE", 409,
                       "Pay requires payout status AUTHORIZED")
    wave = db.waves[a["wave_id"]]
    wave["incentive_pool_reserved_cents"] -= a["amount_cents"]
    wave["incentive_pool_paid_cents"] += a["amount_cents"]
    touch(wave)
    a["payout_status"] = "PAID"
    touch(a)
    return ok(ser_award(a))


@bp.post("/feedback-panel/incentive-awards/<award_id>/forfeit")
@require_roles("IncentiveClerk")
def forfeit(award_id):
    a = get_award_or_404(award_id)
    if a["payout_status"] != "AUTHORIZED":
        raise ApiError("ERR_AWARD_NOT_FORFEIT_STATE", 409,
                       "Forfeit requires payout status AUTHORIZED")
    wave = db.waves[a["wave_id"]]
    wave["incentive_pool_reserved_cents"] -= a["amount_cents"]
    wave["incentive_pool_available_cents"] += a["amount_cents"]
    touch(wave)
    a["payout_status"] = "FORFEITED"
    touch(a)
    return ok(ser_award(a))
