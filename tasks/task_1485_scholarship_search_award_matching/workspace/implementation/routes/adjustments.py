"""Award adjustments (PRD §3.8)."""

from flask import Blueprint, g, request

import db
from errors import raise_err
from middleware import require_roles, body
from response import success, paginate, sort_default
from services import engine
from services.validate import require_fields, req_enum, req_int

bp = Blueprint("adjustments", __name__)

REASONS = {"OVER_AWARD", "DUPLICATE", "DATA_ERROR", "WITHDRAWAL"}
ADJ_ROLES = ("ScholarshipCoordinator", "FinancialAidOfficer")


def get_adjustment_or_404(aid):
    a = db.get("adjustments", aid)
    if a is None:
        raise_err("ERR_NOT_FOUND", "AwardAdjustment not found")
    return a


@bp.route("/api/award-adjustments", methods=["POST"])
@require_roles(*ADJ_ROLES)
def create_adjustment():
    data = body()
    require_fields(data, ["award_id", "reason", "delta_cents"])
    award_id = data["award_id"]
    if not isinstance(award_id, str) or db.get("awards", award_id) is None:
        raise_err("ERR_NOT_FOUND", "Award not found")
    reason = req_enum(data, "reason", REASONS)
    delta = data["delta_cents"]
    if not isinstance(delta, int) or isinstance(delta, bool) or delta == 0:
        raise_err("ERR_VALIDATION", "delta_cents must be a non-zero integer")
    rec = db.create_record("adjustments", {
        "award_id": award_id,
        "reason": reason,
        "delta_cents": delta,
        "status": "DRAFT",
        "auto_generated": False,
        "created_by_user_id": g.user_id,
        "approved_by_user_id": None,
    })
    return success(db.serialize(rec), code=201)


@bp.route("/api/award-adjustments", methods=["GET"])
@require_roles(*ADJ_ROLES)
def list_adjustments():
    items = db.all_records("adjustments")
    award_id = request.args.get("award_id")
    status = request.args.get("status")
    if award_id is not None:
        items = [a for a in items if a["award_id"] == award_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sort_default(items)
    page, meta = paginate(items)
    return success([db.serialize(a) for a in page], response_type="array", pagination=meta)


@bp.route("/api/award-adjustments/<aid>", methods=["GET"])
@require_roles(*ADJ_ROLES)
def get_adjustment(aid):
    return success(db.serialize(get_adjustment_or_404(aid)))


@bp.route("/api/award-adjustments/<aid>/submit", methods=["POST"])
@require_roles(*ADJ_ROLES)
def submit_adjustment(aid):
    adj = get_adjustment_or_404(aid)
    if adj["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Only a DRAFT adjustment can be submitted")
    db.mutate(adj, status="PENDING_APPROVAL")
    return success(db.serialize(adj))


@bp.route("/api/award-adjustments/<aid>/approve", methods=["POST"])
@require_roles("FinancialAidOfficer")
def approve_adjustment(aid):
    adj = get_adjustment_or_404(aid)
    if adj["status"] != "PENDING_APPROVAL":
        raise_err("ERR_INVALID_STATE", "Only a PENDING_APPROVAL adjustment can be approved")
    if adj["created_by_user_id"] is not None and g.user_id == adj["created_by_user_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES", "The approver must differ from the creator")
    award = db.get("awards", adj["award_id"])
    if award is None:
        raise_err("ERR_NOT_FOUND", "Award not found")
    new_amount = award["amount_cents"] + adj["delta_cents"]
    if new_amount <= 0:
        raise_err("ERR_VALIDATION", "Resulting award amount_cents must remain positive")
    net = engine.net_confirmed(award["id"])
    if adj["reason"] in ("DUPLICATE", "DATA_ERROR") and new_amount < net:
        raise_err("ERR_ADJUSTMENT_EXCEEDS_DISBURSED",
                  "Clawback would cut below money already confirmed")
    db.mutate(adj, status="APPLIED", approved_by_user_id=g.user_id)
    db.mutate(award, amount_cents=new_amount)
    if award["offer_status"] == "ACCEPTED" and net > new_amount:
        db.mutate(award, funding_status="OVER_DISBURSED")
    program = engine.program_of_award(award)
    engine.recompute_fund(db.get("award_funds", program["fund_id"]))
    engine.stacking_recompute(db.get("students", award["student_id"]), program)
    return success(db.serialize(adj))


@bp.route("/api/award-adjustments/<aid>/reject", methods=["POST"])
@require_roles("FinancialAidOfficer")
def reject_adjustment(aid):
    adj = get_adjustment_or_404(aid)
    if adj["status"] != "PENDING_APPROVAL":
        raise_err("ERR_INVALID_STATE", "Only a PENDING_APPROVAL adjustment can be rejected")
    if adj["created_by_user_id"] is not None and g.user_id == adj["created_by_user_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES", "The rejector must differ from the creator")
    db.mutate(adj, status="REJECTED")
    return success(db.serialize(adj))
