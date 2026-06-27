from flask import Blueprint, request

from db import db, base_fields, bump
from middleware import get_auth, require_role
from validators import get_body, req_str, opt_str
from errors import err
from response import success
from pagination import paginate
import serializers as S
import services as svc
import derive
import calculations as calc

bp = Blueprint("content", __name__)


@bp.route("/content-submissions", methods=["POST"])
def submit_content():
    user_id, role = get_auth()
    require_role(role, {"Creator"})
    body = get_body()
    deliverable_id = req_str(body, "deliverable_id", allow_empty=False)
    contract_id = req_str(body, "contract_id", allow_empty=False)
    media_url = req_str(body, "media_url", allow_empty=False)
    caption = opt_str(body, "caption", default=None)

    # existence (priority 4)
    deliverable = svc.get_deliverable(deliverable_id)
    contract = svc.get_contract(contract_id)

    # ownership: creator owns the contract via creator_id (PRD 2.1)
    if contract["creator_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting creator does not own this contract")

    # referential: deliverable & contract belong to same campaign (priority 15)
    if deliverable["campaign_id"] != contract["campaign_id"]:
        raise err("ERR_DELIVERABLE_CONTRACT_MISMATCH",
                  "Deliverable and contract belong to different campaigns")

    rec = base_fields()
    rec.update({
        "deliverable_id": deliverable_id,
        "contract_id": contract_id,
        "media_url": media_url,
        "caption": caption,
        "has_ftc_disclosure": calc.detect_ftc(caption),
        "revision_count": 0,
        "status": "SUBMITTED",
    })
    db.content_submissions[rec["id"]] = rec
    return success(S.content_submission_view(rec), status=201)


@bp.route("/content-submissions/<sub_id>", methods=["GET"])
def get_submission(sub_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "Creator", "ComplianceOfficer"})
    s = svc.get_content_submission(sub_id)
    return success(S.content_submission_view(s), status=200)


@bp.route("/content-submissions", methods=["GET"])
def list_submissions():
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "Creator", "ComplianceOfficer"})
    deliverable_id = request.args.get("deliverable_id")
    contract_id = request.args.get("contract_id")
    status = request.args.get("status")
    rows = list(db.content_submissions.values())
    if deliverable_id is not None:
        rows = [s for s in rows if s["deliverable_id"] == deliverable_id]
    if contract_id is not None:
        rows = [s for s in rows if s["contract_id"] == contract_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    page, meta = paginate(rows)
    return success([S.content_submission_view(s) for s in page], status=200, pagination=meta)


@bp.route("/content-submissions/<sub_id>/start-review", methods=["POST"])
def start_review(sub_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    s = svc.get_content_submission(sub_id)
    if s["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Only a SUBMITTED submission can enter review")
    contract = db.contracts.get(s["contract_id"])
    if not contract or contract["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Parent contract is not ACTIVE")
    s["status"] = "IN_REVIEW"
    bump(s)
    return success(S.content_submission_view(s), status=200)


@bp.route("/content-submissions/<sub_id>/request-changes", methods=["POST"])
def request_changes(sub_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    s = svc.get_content_submission(sub_id)
    if s["status"] != "IN_REVIEW":
        raise err("ERR_INVALID_STATE", "Only an IN_REVIEW submission can have changes requested")
    if s["revision_count"] >= calc.MAX_REVISION_ROUNDS:
        raise err("ERR_INVALID_STATE", "Revision cap reached")
    s["status"] = "CHANGES_REQUESTED"
    s["revision_count"] += 1
    bump(s)
    return success(S.content_submission_view(s), status=200)


@bp.route("/content-submissions/<sub_id>/resubmit", methods=["POST"])
def resubmit(sub_id):
    user_id, role = get_auth()
    require_role(role, {"Creator"})
    s = svc.get_content_submission(sub_id)
    contract = db.contracts.get(s["contract_id"])
    # ownership: acting Creator owns the contract of this submission
    if not contract or contract["creator_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting creator does not own this submission")
    body = get_body()
    media_url = req_str(body, "media_url", allow_empty=False)
    caption = opt_str(body, "caption", default=None)

    if s["status"] != "CHANGES_REQUESTED":
        raise err("ERR_INVALID_STATE", "Only a CHANGES_REQUESTED submission can be resubmitted")
    if contract["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Parent contract is not ACTIVE")

    s["media_url"] = media_url
    s["caption"] = caption
    s["has_ftc_disclosure"] = calc.detect_ftc(caption)
    s["status"] = "SUBMITTED"
    bump(s)
    return success(S.content_submission_view(s), status=200)


@bp.route("/content-submissions/<sub_id>/approve", methods=["POST"])
def approve(sub_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    s = svc.get_content_submission(sub_id)
    if s["status"] != "IN_REVIEW":
        raise err("ERR_INVALID_STATE", "Only an IN_REVIEW submission can be approved")
    contract = db.contracts.get(s["contract_id"])
    campaign = db.campaigns.get(contract["campaign_id"]) if contract else None
    creator = db.creators.get(contract["creator_id"]) if contract else None

    # brand-safety (priority 11) and FTC (priority 12). PRD order at approve:
    # FTC check then brand-safety per workflow text. Validation table lists brand
    # safety (11) before FTC (12); apply that ordering.
    if creator:
        derive.recompute_brand_safety_status(creator)
        if creator["brand_safety_status"] == "BLOCKED":
            raise err("ERR_BRAND_SAFETY_BLOCKED", "Creator is BLOCKED on brand safety")
    if campaign and campaign["requires_ftc_disclosure"] and not s["has_ftc_disclosure"]:
        raise err("ERR_FTC_DISCLOSURE_MISSING", "FTC disclosure missing")

    s["status"] = "APPROVED"
    bump(s)

    # bubble-up: maybe fulfill the contract
    if contract:
        svc.maybe_fulfill_contract(contract)

    return success(S.content_submission_view(s), status=200)


@bp.route("/content-submissions/<sub_id>/reject", methods=["POST"])
def reject(sub_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    s = svc.get_content_submission(sub_id)
    if s["status"] != "CHANGES_REQUESTED":
        raise err("ERR_INVALID_STATE", "Only a CHANGES_REQUESTED submission can be rejected")
    if s["revision_count"] < calc.MAX_REVISION_ROUNDS:
        raise err("ERR_INVALID_STATE", "Rejection only allowed once the revision cap is reached")
    s["status"] = "REJECTED"
    bump(s)
    return success(S.content_submission_view(s), status=200)
