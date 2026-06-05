"""TotalLossEvaluation routes (PRD §3.5)."""
from flask import Blueprint, request

import db
import serializers as S
from auth import authenticate, authorize
from errors import err
from helpers import (get_json_body, require_resource, require_fields,
                     optional_bool, parse_pagination, paginate)
from response import success, list_success
from services import calc
from services.lookups import submitted_estimate

bp = Blueprint("total_loss_evaluations", __name__)

READ_ROLES = {"ClaimsSupervisor", "ClaimsAdjuster", "TotalLossAdjuster"}


@bp.route("/total-loss-evaluations", methods=["POST"])
def create_total_loss_evaluation():
    principal = authenticate()
    authorize(principal, {"TotalLossAdjuster"})
    body = get_json_body()
    require_fields(body, ["claim_id"])
    claim = require_resource(db.claims, body["claim_id"], "claim")
    salvage_retained = optional_bool(body, "salvage_retained_by_insurer", True)

    # Author must be a SENIOR-tier adjuster (X-User-ID is the Adjuster id).
    adjuster = db.adjusters.get(principal.user_id)
    if adjuster is None:
        raise err("ERR_NOT_FOUND", "acting adjuster not found")
    if adjuster["license_tier"] != "SENIOR":
        raise err("ERR_SENIOR_TIER_REQUIRED",
                  "only a SENIOR-tier adjuster may author a total-loss evaluation")

    estimate = submitted_estimate(claim["id"])
    repair_total_snapshot = estimate["repair_total_cents"] if estimate else 0
    acv_snapshot = claim["vehicle_acv_cents"]
    ratio, is_total = calc.total_loss_decision(repair_total_snapshot, acv_snapshot)

    rec = {
        "claim_id": claim["id"],
        "evaluated_by_adjuster_id": principal.user_id,
        "acv_cents": acv_snapshot,
        "repair_total_cents": repair_total_snapshot,
        "total_loss_ratio": ratio,
        "is_total_loss": is_total,
        "salvage_retained_by_insurer": salvage_retained,
    }
    db.insert(db.total_loss_evaluations, rec)
    return success(S.total_loss_evaluation(rec), status=201)


@bp.route("/total-loss-evaluations/<tid>", methods=["GET"])
def get_total_loss_evaluation(tid):
    principal = authenticate()
    authorize(principal, READ_ROLES)
    rec = require_resource(db.total_loss_evaluations, tid, "total-loss evaluation")
    return success(S.total_loss_evaluation(rec), status=200)


@bp.route("/total-loss-evaluations", methods=["GET"])
def list_total_loss_evaluations():
    principal = authenticate()
    authorize(principal, READ_ROLES)
    limit, offset = parse_pagination()
    claim_id = request.args.get("claim_id")
    evaluated_by = request.args.get("evaluated_by_adjuster_id")
    rows = list(db.total_loss_evaluations.values())
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if evaluated_by is not None:
        rows = [r for r in rows if r["evaluated_by_adjuster_id"] == evaluated_by]
    page, total = paginate(rows, limit, offset)
    return list_success([S.total_loss_evaluation(r) for r in page], limit, offset, total)
