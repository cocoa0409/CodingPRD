"""ReferralBonus routes — list, read, pay."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import require_auth
from ..common import bump, paginate_list, parse_pagination
from ..errors import ApiError
from ..lookups import path_referral_bonus
from ..response import respond
from ..serializers import serialize_referral_bonus
from ..store import store


referral_bonuses_bp = Blueprint("referral_bonuses", __name__)


@referral_bonuses_bp.get("/referral-bonuses")
@require_auth("Recruiter", "PayrollOperator", "PlatformAdmin")
def list_referral_bonuses():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    referrer = request.args.get("referrer_employee_id")
    candidate_id = request.args.get("candidate_id")
    with store.lock:
        items = sorted(store.referral_bonuses.values(), key=lambda r: r["created_at"])
        if status:
            items = [r for r in items if r["status"] == status]
        if referrer:
            items = [r for r in items if r.get("referrer_employee_id") == referrer]
        if candidate_id:
            items = [r for r in items if r["candidate_id"] == candidate_id]
        page, meta = paginate_list(items, limit, offset)
        return respond([serialize_referral_bonus(r) for r in page], list_meta=meta)


@referral_bonuses_bp.get("/referral-bonuses/<rid>")
@require_auth("Recruiter", "PayrollOperator", "PlatformAdmin")
def get_referral_bonus(rid):
    with store.lock:
        return respond(serialize_referral_bonus(path_referral_bonus(rid)))


@referral_bonuses_bp.post("/referral-bonuses/<rid>/pay")
@require_auth("PayrollOperator")
def pay_referral_bonus(rid):
    with store.lock:
        rb = path_referral_bonus(rid)
        if rb["status"] != "PAYABLE":
            raise ApiError("ERR_INVALID_STATE", "ReferralBonus is not PAYABLE")
        # Linked application must still be HIRED.
        linked = None
        for app in store.applications.values():
            if app["candidate_id"] == rb["candidate_id"] and app["requisition_id"] == rb["requisition_id"]:
                linked = app
                break
        if linked is None or linked["stage"] != "HIRED":
            raise ApiError("ERR_INVALID_STATE", "Linked application must still be HIRED")
        rb["status"] = "PAID"
        bump(rb)
        return respond(serialize_referral_bonus(rb))
