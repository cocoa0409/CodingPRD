"""BackgroundCheck endpoints + resolve cascade."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
from auth import require_role
from common import (
    get_json_or_400,
    require_enum,
    parse_pagination,
    paginate,
    get_or_404,
    stamp_update,
    now_iso,
)
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_BGC_INDEPENDENCE,
)
from response import success_object, success_array
from serializers import ser_background_check
from services.cascades import (
    transition_application_to_rejected,
    void_referral_bonus_for_offer,
    find_referral_bonus_by_offer,
    maybe_reopen_requisition,
)
from services.referral import payable_amount


bp = Blueprint("background_checks", __name__)


@bp.get("/ats/background-checks/<bgc_id>")
def read_bgc(bgc_id):
    require_role({"ComplianceOfficer", "HiringManager", "PlatformAdmin"})
    bgc = get_or_404(db.background_checks, bgc_id, "background check")
    return success_object(ser_background_check(bgc), status=200)


@bp.get("/ats/background-checks")
def list_bgcs():
    require_role({"ComplianceOfficer", "HiringManager", "PlatformAdmin"})
    limit, offset = parse_pagination()
    rows = list(db.background_checks.values())
    offer_f = request.args.get("offer_id")
    cand_f = request.args.get("candidate_id")
    status_f = request.args.get("status")
    if offer_f:
        rows = [b for b in rows if b["offer_id"] == offer_f]
    if cand_f:
        rows = [b for b in rows if b["candidate_id"] == cand_f]
    if status_f:
        rows = [b for b in rows if b["status"] == status_f]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return success_array([ser_background_check(b) for b in page], limit, offset, total, status=200)


@bp.post("/ats/background-checks/<bgc_id>/start")
def start_bgc(bgc_id):
    require_role({"ComplianceOfficer"})
    bgc = get_or_404(db.background_checks, bgc_id, "background check")
    if bgc["status"] != "INITIATED":
        raise ApiError(ERR_INVALID_STATE, 409, "background check not in INITIATED")
    bgc["status"] = "IN_PROGRESS"
    stamp_update(bgc)
    return success_object(ser_background_check(bgc), status=200)


@bp.post("/ats/background-checks/<bgc_id>/resolve")
def resolve_bgc(bgc_id):
    uid, _ = require_role({"ComplianceOfficer"})
    bgc = get_or_404(db.background_checks, bgc_id, "background check")
    body = get_json_or_400()
    outcome = require_enum(body, "outcome", {"PASSED", "FAILED"})

    if bgc["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "background check not in IN_PROGRESS")

    # Independence: resolver must not be requisition submitter or approver.
    offer = db.offers.get(bgc["offer_id"])
    app = db.applications.get(offer["application_id"]) if offer else None
    req = db.requisitions.get(app["requisition_id"]) if app else None
    if req:
        if uid == req.get("submitter_user_id") or uid == req.get("approver_user_id"):
            raise ApiError(ERR_BGC_INDEPENDENCE, 403, "resolver must be independent of requisition submitter/approver")

    bgc["completed_at"] = now_iso()

    if outcome == "PASSED":
        bgc["status"] = "PASSED"
        stamp_update(bgc)
        # Cascade ReferralBonus PENDING_BGC -> PAYABLE, recompute payable_amount_cents.
        rb = find_referral_bonus_by_offer(offer["id"]) if offer else None
        if rb and rb["status"] == "PENDING_BGC":
            candidate = db.candidates[rb["candidate_id"]]
            req_obj = db.requisitions[db.applications[offer["application_id"]]["requisition_id"]]
            # delay = floor((bgc.completed_at - offer.accepted_at) / 1 day).
            accepted_at_dt = clock.parse_iso(offer["accepted_at"])
            completed_at_dt = clock.parse_iso(bgc["completed_at"])
            delta = completed_at_dt - accepted_at_dt
            delay_days = int(delta.total_seconds() // 86400)
            if delay_days < 0:
                delay_days = 0
            new_payable = payable_amount(offer, candidate, req_obj, delay_days)
            rb["payable_amount_cents"] = new_payable
            rb["status"] = "PAYABLE"
            stamp_update(rb)
    else:
        # FAILED outcome: rollback hire.
        bgc["status"] = "FAILED"
        stamp_update(bgc)
        if offer:
            old_status = offer["status"]
            if old_status in {"EXTENDED", "ACCEPTED"}:
                offer["status"] = "REVOKED"
                stamp_update(offer)
            if app and app["status"] == "HIRED":
                # Reject hired application; requisition.filled_count is computed off applications.
                transition_application_to_rejected(app["id"])
                # If req was CLOSED, possibly re-open to APPROVED.
                if req:
                    maybe_reopen_requisition(req["id"])
            void_referral_bonus_for_offer(offer["id"])
    return success_object(ser_background_check(bgc), status=200)
