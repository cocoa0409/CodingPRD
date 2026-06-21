"""DayPass read + refund endpoints (PRD §3.6)."""
from flask import Blueprint

import errors
import domain
from db import db, touch
from middleware import get_principal, require_role
from serializers import serialize
from response import success
from routes.common import list_filtered

bp = Blueprint("day_passes", __name__)


@bp.route("/day-passes", methods=["GET"])
def list_day_passes():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member", "LoungeAgent"})
    return list_filtered(
        db.day_passes,
        [
            ("lounge_id", "lounge_id", "str"),
            ("member_id", "member_id", "str"),
            ("redeemed_visit_id", "redeemed_visit_id", "str"),
            ("status", "status", "str"),
        ],
    )


@bp.route("/day-passes/<day_pass_id>", methods=["GET"])
def get_day_pass(day_pass_id):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member", "LoungeAgent"})
    dp = domain.get_day_pass(day_pass_id)
    if not dp:
        raise errors.not_found("Day pass not found")
    return success(serialize(dp))


@bp.route("/day-passes/<day_pass_id>/refund", methods=["POST"])
def refund_day_pass(day_pass_id):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    dp = domain.get_day_pass(day_pass_id)
    if not dp:
        raise errors.not_found("Day pass not found")
    # state: only ISSUED (never redeemed) may be refunded
    if dp["status"] != "ISSUED":
        raise errors.invalid_state("Day pass is not ISSUED")
    # member-owned only
    if dp.get("member_id") is None:
        raise errors.invalid_state("Only member-owned passes may be refunded")

    dp["status"] = "REFUNDED"
    touch(dp)

    member = domain.get_member(dp["member_id"])
    domain.post_ledger_entry(
        dp["member_id"], "DAY_PASS_REFUND", -dp["price_cents"],
        day_pass_id=dp["id"]
    )
    if member:
        domain.recompute_wallet(member)

    return success(serialize(dp))
