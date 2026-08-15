"""Due diligence milestone routes (PRD §3.5)."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import bump, require_role
from response import ok, ok_list
from services import domain

bp = Blueprint("milestones", __name__)

# CapitalMarketsOfficer is excluded from the milestone read surface.
READ_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "DueDiligenceOfficer",
              "EscrowOfficer", "AssetManager", "PlatformAdmin")


@bp.route("/acquisition-deals/deals/<deal_id>/milestones", methods=["GET"])
def list_milestones(deal_id):
    require_role(*READ_ROLES)
    deal = domain.get_deal(deal_id)
    items = domain.milestones_of(deal["id"])
    for param in ("status", "milestone_type"):
        v = request.args.get(param)
        if v is not None:
            items = [m for m in items if str(m.get(param)) == v]
    return ok_list(items)


@bp.route("/acquisition-deals/deals/<deal_id>/milestones/<milestone_id>", methods=["GET"])
def get_milestone(deal_id, milestone_id):
    require_role(*READ_ROLES)
    deal = domain.get_deal(deal_id)
    return ok(db.pub(domain.get_milestone_scoped(deal, milestone_id)))


@bp.route("/acquisition-deals/deals/<deal_id>/milestones/<milestone_id>/start", methods=["POST"])
def start_milestone(deal_id, milestone_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    m = domain.get_milestone_scoped(deal, milestone_id)
    if m["status"] != "PENDING":
        raise ApiError("ERR_MILESTONE_INVALID_STATE",
                       "start requires milestone status PENDING", 409)
    if deal["status"] not in ("PSA_EXECUTED", "DUE_DILIGENCE"):
        raise ApiError("ERR_DEAL_INVALID_STATE",
                       "Milestones can start only while the deal is PSA_EXECUTED or DUE_DILIGENCE", 409)
    m["status"] = "IN_PROGRESS"
    bump(m)
    if deal["status"] == "PSA_EXECUTED":
        deal["status"] = "DUE_DILIGENCE"
        bump(deal)
    return ok(db.pub(m))


@bp.route("/acquisition-deals/deals/<deal_id>/milestones/<milestone_id>/complete", methods=["POST"])
def complete_milestone(deal_id, milestone_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    m = domain.get_milestone_scoped(deal, milestone_id)
    if m["status"] != "IN_PROGRESS":
        raise ApiError("ERR_MILESTONE_INVALID_STATE",
                       "complete requires milestone status IN_PROGRESS", 409)
    m["status"] = "SATISFIED"
    m["completed_at"] = db.now_iso()
    bump(m)
    domain.recompute_posture(deal)
    return ok(db.pub(m))


@bp.route("/acquisition-deals/deals/<deal_id>/milestones/<milestone_id>/waive", methods=["POST"])
def waive_milestone(deal_id, milestone_id):
    require_role("UnderwritingCommittee")
    deal = domain.get_deal(deal_id)
    m = domain.get_milestone_scoped(deal, milestone_id)
    if m["status"] not in ("PENDING", "IN_PROGRESS"):
        raise ApiError("ERR_MILESTONE_INVALID_STATE",
                       "waive requires milestone status PENDING or IN_PROGRESS", 409)
    if m["milestone_type"] in domain.NON_WAIVABLE_MILESTONES:
        raise ApiError("ERR_MILESTONE_NOT_WAIVABLE",
                       "TITLE_REVIEW and ENVIRONMENTAL milestones cannot be waived", 422)
    m["status"] = "WAIVED"
    m["waived"] = True
    bump(m)
    domain.recompute_posture(deal)
    return ok(db.pub(m))
