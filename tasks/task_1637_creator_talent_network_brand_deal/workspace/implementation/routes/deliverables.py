"""Deliverable endpoints: get, submit, review, publish; nested disclosure
checks and reshoots listing/creation."""

from flask import Blueprint, request

import db
import errors as err
import response as resp
from middleware import require_roles, require_owner
from services import helpers as H

bp = Blueprint("deliverables", __name__)

DELIVERABLE_TERMINAL = {"VERIFIED", "CANCELLED"}


def _deal_of(deliverable):
    return H.get_or_404(db.deals, deliverable["deal_id"], "deal")


def _check_owner(actor, deliverable):
    deal = db.deals.get(deliverable["deal_id"])
    if deal is None:
        return
    if actor.role == "Creator":
        require_owner(actor, deal["creator_id"], "deal")
    elif actor.role == "Brand":
        require_owner(actor, deal["brand_id"], "deal")


@bp.route("/deliverables/<did>", methods=["GET"])
@require_roles("BrandManager", "TalentManager", "Creator", "Brand",
               "ComplianceOfficer")
def get_deliverable(actor, did):
    deliverable = H.get_or_404(db.deliverables, did, "deliverable")
    _check_owner(actor, deliverable)
    return resp.ok(deliverable)


@bp.route("/deliverables/<did>/submit", methods=["POST"])
@require_roles("Creator")
def submit_deliverable(actor, did):
    deliverable = H.get_or_404(db.deliverables, did, "deliverable")
    deal = _deal_of(deliverable)
    require_owner(actor, deal["creator_id"], "deal")
    H.body()

    if (deal["status"] == "TERMINATED"
            or deliverable["status"] in DELIVERABLE_TERMINAL):
        raise err.already_terminal(
            "Deal is terminated or deliverable is in a terminal state")
    if deal["status"] != "ACTIVE":
        raise err.invalid_state("Submission requires deal ACTIVE")
    if deliverable["status"] not in ("PENDING_SUBMISSION", "REVISION_REQUESTED"):
        raise err.invalid_state(
            f"Deliverable cannot be submitted from {deliverable['status']}")

    deliverable["status"] = "IN_REVIEW"
    H.touch(deliverable)
    return resp.ok(deliverable)


@bp.route("/deliverables/<did>/review", methods=["POST"])
@require_roles("BrandManager")
def review_deliverable(actor, did):
    deliverable = H.get_or_404(db.deliverables, did, "deliverable")
    payload = H.body()
    H.req_fields(payload, ["action"])
    action = H.require_enum(payload, "action", {"APPROVE", "REQUEST_REVISION"})
    deal = _deal_of(deliverable)

    if (deal["status"] == "TERMINATED"
            or deliverable["status"] in DELIVERABLE_TERMINAL):
        raise err.already_terminal(
            "Deal is terminated or deliverable is in a terminal state")
    if deal["status"] != "ACTIVE":
        raise err.invalid_state("Review requires deal ACTIVE")
    if deliverable["status"] != "IN_REVIEW":
        raise err.invalid_state("Review requires deliverable IN_REVIEW")

    if action == "APPROVE":
        deliverable["status"] = "APPROVED"
        deliverable["reviewed_by_user_id"] = actor.user_id
        H.touch(deliverable)
        return resp.ok(deliverable)

    # REQUEST_REVISION — priority 15.
    if deliverable["revision_rounds_used"] >= int(deal["revision_rounds_included"]):
        raise err.ApiError(err.ERR_REVISION_LIMIT_EXCEEDED,
                           "Revision rounds exhausted for this deliverable",
                           422)
    deliverable["revision_rounds_used"] += 1
    deliverable["status"] = "REVISION_REQUESTED"
    H.touch(deliverable)
    return resp.ok(deliverable)


@bp.route("/deliverables/<did>/publish", methods=["POST"])
@require_roles("Creator")
def publish_deliverable(actor, did):
    deliverable = H.get_or_404(db.deliverables, did, "deliverable")
    deal = _deal_of(deliverable)
    require_owner(actor, deal["creator_id"], "deal")
    payload = H.body()
    H.req_fields(payload, ["content_url"])
    content_url = H.require_str(payload, "content_url")

    if (deal["status"] == "TERMINATED"
            or deliverable["status"] in DELIVERABLE_TERMINAL):
        raise err.already_terminal(
            "Deal is terminated or deliverable is in a terminal state")
    if deliverable["status"] != "APPROVED":
        raise err.invalid_state("Publish requires deliverable APPROVED")
    if deal["status"] != "ACTIVE":
        raise err.invalid_state("Publish requires deal ACTIVE")

    # Priority 10: compliance gate.
    creator = db.creators.get(deal["creator_id"])
    if (creator is None or creator["status"] != "ACTIVE"
            or int(creator.get("compliance_strikes", 0)) >= H.STRIKE_LIMIT):
        raise err.ApiError(err.ERR_CREATOR_COMPLIANCE_SUSPENDED,
                           "Creator is not in good compliance standing", 422)

    # Priority 24: publish window (both bounds inclusive).
    brief = db.briefs.get(deal["brief_id"])
    now = db.get_clock()
    if brief is not None:
        cw_start = db.parse_iso(brief["content_window_start"])
        cw_end = db.parse_iso(brief["content_window_end"])
        if not (cw_start <= now <= cw_end):
            raise err.ApiError(err.ERR_PUBLISH_WINDOW_VIOLATION,
                               "Publish attempted outside the brief content "
                               "window", 422)

    deliverable["content_url"] = content_url
    deliverable["published_at"] = db.now_iso()
    deliverable["status"] = "PUBLISHED"
    H.touch(deliverable)

    # Cascade: spawn a QUEUED disclosure check and recompute pending count.
    check = H.new_entity()
    check.update({
        "deliverable_id": deliverable["id"],
        "status": "QUEUED",
        "recheck_count": 0,
        "has_ad_hashtag": False,
        "verbal_disclosure": False,
        "platform_tool_used": False,
        "checked_by_user_id": None,
        "checked_at": None,
    })
    db.disclosure_checks[check["id"]] = check
    H.recompute_pending_disclosure_count(deal["creator_id"])

    return resp.ok(deliverable)


@bp.route("/deliverables/<did>/disclosure-checks", methods=["GET"])
@require_roles("ComplianceOfficer", "BrandManager", "Creator")
def list_disclosure_checks(actor, did):
    deliverable = H.get_or_404(db.deliverables, did, "deliverable")
    _check_owner(actor, deliverable)
    items = [c for c in db.disclosure_checks.values()
             if c["deliverable_id"] == did]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return resp.paginate(items, request.args)


@bp.route("/deliverables/<did>/reshoots", methods=["GET"])
@require_roles("BrandManager", "Creator", "TalentManager")
def list_reshoots(actor, did):
    deliverable = H.get_or_404(db.deliverables, did, "deliverable")
    _check_owner(actor, deliverable)
    items = [r for r in db.reshoots.values() if r["deliverable_id"] == did]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return resp.paginate(items, request.args)


@bp.route("/deliverables/<did>/reshoots", methods=["POST"])
@require_roles("BrandManager")
def request_reshoot(actor, did):
    deliverable = H.get_or_404(db.deliverables, did, "deliverable")
    payload = H.body()
    H.req_fields(payload, ["reason"])
    reason = H.require_str(payload, "reason")
    dispute_id = H.opt_str(payload, "dispute_id", default=None)
    if dispute_id is not None:
        H.get_or_404(db.disputes, dispute_id, "dispute")

    deal = _deal_of(deliverable)
    if deliverable["status"] == "CANCELLED":
        raise err.already_terminal("Deliverable is CANCELLED")
    if deal["status"] in ("COMPLETED", "TERMINATED"):
        raise err.already_terminal(f"Deal is {deal['status']}")
    if deal["status"] not in ("ACTIVE", "IN_DISPUTE"):
        raise err.invalid_state(
            "Reshoot requests require deal ACTIVE or IN_DISPUTE")
    if deliverable["status"] not in ("APPROVED", "PUBLISHED", "VERIFIED"):
        raise err.invalid_state(
            "Reshoot requires deliverable APPROVED, PUBLISHED, or VERIFIED")

    if int(deliverable.get("reshoot_count", 0)) >= H.MAX_RESHOOTS_PER_DELIVERABLE:
        raise err.ApiError(err.ERR_RESHOOT_LIMIT_EXCEEDED,
                           "Reshoot limit reached for this deliverable", 422)

    reshoot = H.new_entity()
    reshoot.update({
        "deliverable_id": deliverable["id"],
        "dispute_id": dispute_id,
        "reason": reason,
        "status": "REQUESTED",
        "responded_at": None,
    })
    db.reshoots[reshoot["id"]] = reshoot
    return resp.created(reshoot)
