"""Claim adjustment endpoints."""

from flask import Blueprint, request

from db import stores
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_TRIGGERING_DET_NOT_FINAL,
)
from helpers import base_record, touch, get_or_404, body, req_enum, opt_str, paginate
from middleware import require_roles
from response import success
from services.calculations import compute_claim_payment, primary_is_ours_for_determination

bp = Blueprint("adjustments", __name__)

CAUSES = (
    "NEW_COVERAGE_DISCOVERED", "PRIMACY_DETERMINATION_SUPERSEDED",
    "MSP_QUESTIONNAIRE_ADJUDICATED", "MANUAL_REVIEW",
)


def _get_nested_adjustment(cid, aid):
    get_or_404(stores["claims"], cid, "claim")
    adj = stores["adjustments"].get(aid)
    if adj is None or adj.get("claim_id") != cid:
        raise_err(ERR_NOT_FOUND, "adjustment does not exist or does not belong to claim")
    return adj


@bp.route("/cob/claims/<cid>/adjustments", methods=["POST"])
def create_adjustment(cid):
    require_roles("ClaimsExaminer", "COBAnalyst")
    get_or_404(stores["claims"], cid, "claim")
    data = body()
    cause = req_enum(data, "cause", CAUSES)
    trig = opt_str(data, "triggering_determination_id", None)
    rec = base_record()
    rec.update({
        "claim_id": cid,
        "cause": cause,
        "triggering_determination_id": trig,
        "pre_paid_cents": None,
        "post_paid_cents": None,
        "overpayment_cents": None,
        "underpayment_cents": None,
        "status": "DRAFT",
    })
    stores["adjustments"][rec["id"]] = rec
    return success(rec, status=201)


@bp.route("/cob/claims/<cid>/adjustments", methods=["GET"])
def list_adjustments(cid):
    require_roles("PlatformAdmin", "ClaimsExaminer", "COBAnalyst", "RecoverySpecialist", "COBAuditor")
    get_or_404(stores["claims"], cid, "claim")
    items = [a for a in stores["adjustments"].values() if a.get("claim_id") == cid]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a.get("status") == status]
    return paginate(items)


@bp.route("/cob/claims/<cid>/adjustments/<aid>", methods=["GET"])
def get_adjustment(cid, aid):
    require_roles("PlatformAdmin", "ClaimsExaminer", "COBAnalyst", "RecoverySpecialist", "COBAuditor")
    adj = _get_nested_adjustment(cid, aid)
    return success(adj)


@bp.route("/cob/claims/<cid>/adjustments/<aid>/apply", methods=["POST"])
def apply_adjustment(cid, aid):
    require_roles("ClaimsExaminer")
    claim = get_or_404(stores["claims"], cid, "claim")
    adj = _get_nested_adjustment(cid, aid)
    if adj.get("status") != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Adjustment is not in DRAFT")
    if claim.get("status") not in ("PAID", "REOPENED"):
        raise_err(ERR_INVALID_STATE, "claim.status must be PAID or REOPENED")
    trig_id = adj.get("triggering_determination_id")
    if adj.get("cause") == "PRIMACY_DETERMINATION_SUPERSEDED":
        det = stores["determinations"].get(trig_id) if trig_id else None
        if det is None or det.get("status") != "FINALIZED":
            raise_err(ERR_TRIGGERING_DET_NOT_FINAL, "triggering_determination must be FINALIZED")

    pre = claim.get("total_paid_cents", 0)
    # Recompute claim under the triggering determination (or current one)
    det = None
    if trig_id:
        det = stores["determinations"].get(trig_id)
    if det is None and claim.get("primacy_determination_id"):
        det = stores["determinations"].get(claim["primacy_determination_id"])
    if det is not None:
        compute_claim_payment(claim, primary_is_ours_for_determination(det))
    post = claim.get("total_paid_cents", 0)

    adj["pre_paid_cents"] = pre
    adj["post_paid_cents"] = post
    adj["overpayment_cents"] = max(0, pre - post)
    adj["underpayment_cents"] = max(0, post - pre)
    adj["status"] = "APPLIED"
    touch(adj)
    return success(adj)


@bp.route("/cob/claims/<cid>/adjustments/<aid>/void", methods=["POST"])
def void_adjustment(cid, aid):
    require_roles("ClaimsExaminer")
    get_or_404(stores["claims"], cid, "claim")
    adj = _get_nested_adjustment(cid, aid)
    if adj.get("status") != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Adjustment is not in DRAFT")
    adj["status"] = "VOIDED"
    touch(adj)
    return success(adj)


# ---- Top-level reverse-lookup endpoints ----

@bp.route("/cob/adjustments/<aid>", methods=["GET"])
def get_adjustment_top(aid):
    require_roles("PlatformAdmin", "ClaimsExaminer", "COBAnalyst", "RecoverySpecialist", "COBAuditor")
    adj = get_or_404(stores["adjustments"], aid, "adjustment")
    return success(adj)


@bp.route("/cob/adjustments", methods=["GET"])
def list_adjustments_top():
    require_roles("PlatformAdmin", "ClaimsExaminer", "COBAnalyst", "RecoverySpecialist", "COBAuditor")
    items = list(stores["adjustments"].values())
    status = request.args.get("status")
    claim_id = request.args.get("claim_id")
    trig = request.args.get("triggering_determination_id")
    if status:
        items = [a for a in items if a.get("status") == status]
    if claim_id:
        items = [a for a in items if a.get("claim_id") == claim_id]
    if trig:
        items = [a for a in items if a.get("triggering_determination_id") == trig]
    return paginate(items)
