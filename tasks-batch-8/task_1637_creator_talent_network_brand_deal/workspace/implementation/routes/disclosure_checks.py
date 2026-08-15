"""DisclosureCheck endpoints: review (PASS/FAIL with strike cascade) and
requeue."""

from flask import Blueprint

import db
import errors as err
import response as resp
from middleware import require_roles, require_owner
from services import helpers as H, lifecycle

bp = Blueprint("disclosure_checks", __name__)


@bp.route("/disclosure-checks/<cid>/review", methods=["POST"])
@require_roles("ComplianceOfficer")
def review_check(actor, cid):
    check = H.get_or_404(db.disclosure_checks, cid, "disclosure check")
    payload = H.body()
    H.req_fields(payload, ["action"])
    action = H.require_enum(payload, "action", {"PASS", "FAIL"})
    has_ad_hashtag = H.opt_bool(payload, "has_ad_hashtag", default=False)
    verbal_disclosure = H.opt_bool(payload, "verbal_disclosure", default=False)
    platform_tool_used = H.opt_bool(payload, "platform_tool_used", default=False)

    if check["status"] in ("PASSED", "ESCALATED", "VOIDED"):
        raise err.already_terminal(f"DisclosureCheck is {check['status']}")
    if check["status"] != "QUEUED":
        raise err.invalid_state("Review requires check QUEUED")

    deliverable = db.deliverables.get(check["deliverable_id"])
    deal = db.deals.get(deliverable["deal_id"]) if deliverable else None

    if action == "PASS":
        # Priority 5: all checklist flags must be true.
        if not (has_ad_hashtag and verbal_disclosure and platform_tool_used):
            raise err.validation(
                "PASS requires has_ad_hashtag, verbal_disclosure and "
                "platform_tool_used all true")
        # Priority 9: segregation of duties.
        if (deliverable is not None
                and deliverable.get("reviewed_by_user_id") is not None
                and actor.user_id == deliverable["reviewed_by_user_id"]):
            raise err.ApiError(err.ERR_SEGREGATION_OF_DUTIES,
                               "Disclosure reviewer must differ from the "
                               "deliverable approver", 403)

        check["status"] = "PASSED"
        check["has_ad_hashtag"] = has_ad_hashtag
        check["verbal_disclosure"] = verbal_disclosure
        check["platform_tool_used"] = platform_tool_used
        check["checked_by_user_id"] = actor.user_id
        check["checked_at"] = db.now_iso()
        H.touch(check)

        # Bubble-up: deliverable PUBLISHED -> VERIFIED, then maybe deal
        # completion.
        if deliverable is not None and deliverable["status"] == "PUBLISHED":
            deliverable["status"] = "VERIFIED"
            deliverable["verified_at"] = db.now_iso()
            H.touch(deliverable)
            if deal is not None:
                H.recompute_pending_disclosure_count(deal["creator_id"])
                lifecycle.maybe_complete_deal(deal)
        return resp.ok(check)

    # action == "FAIL"
    if int(check.get("recheck_count", 0)) < H.MAX_DISCLOSURE_RECHECKS:
        check["status"] = "FAILED"
        check["has_ad_hashtag"] = has_ad_hashtag
        check["verbal_disclosure"] = verbal_disclosure
        check["platform_tool_used"] = platform_tool_used
        check["checked_by_user_id"] = actor.user_id
        check["checked_at"] = db.now_iso()
        H.touch(check)
        return resp.ok(check)

    # recheck_count == MAX -> ESCALATED + strike cascade.
    check["status"] = "ESCALATED"
    check["has_ad_hashtag"] = has_ad_hashtag
    check["verbal_disclosure"] = verbal_disclosure
    check["platform_tool_used"] = platform_tool_used
    check["checked_by_user_id"] = actor.user_id
    check["checked_at"] = db.now_iso()
    H.touch(check)

    if deal is not None:
        creator = db.creators.get(deal["creator_id"])
        if creator is not None:
            creator["compliance_strikes"] = int(
                creator.get("compliance_strikes", 0)) + 1
            H.touch(creator)
            H.recompute_pending_disclosure_count(creator["id"])
            if (creator["compliance_strikes"] >= H.STRIKE_LIMIT
                    and creator["status"] == "ACTIVE"):
                lifecycle.suspend_creator(creator)
    return resp.ok(check)


@bp.route("/disclosure-checks/<cid>/requeue", methods=["POST"])
@require_roles("Creator")
def requeue_check(actor, cid):
    check = H.get_or_404(db.disclosure_checks, cid, "disclosure check")

    deliverable = db.deliverables.get(check["deliverable_id"])
    deal = db.deals.get(deliverable["deal_id"]) if deliverable else None
    if deal is not None:
        require_owner(actor, deal["creator_id"], "deal")
    H.body()

    if check["status"] in ("PASSED", "ESCALATED", "VOIDED"):
        raise err.already_terminal(f"DisclosureCheck is {check['status']}")
    if check["status"] != "FAILED":
        raise err.invalid_state("Requeue requires check FAILED")

    check["status"] = "QUEUED"
    check["recheck_count"] = int(check.get("recheck_count", 0)) + 1
    H.touch(check)
    return resp.ok(check)
