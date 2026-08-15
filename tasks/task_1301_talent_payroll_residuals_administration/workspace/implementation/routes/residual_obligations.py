"""ResidualObligation endpoints."""

from flask import Blueprint, request

import db
from calculations import (
    find_tier, assign_window_sequence, residual_provisional_amount,
    residual_final_amount,
)
from errors import (
    ApiError, ERR_RESIDUAL_INVALID_STATE, ERR_COMPLIANCE_STATE,
    ERR_RESIDUAL_WINDOW_OVERLAP, ERR_MARKET_BASE_PCT_MISSING, ERR_VALIDATION,
)
from helpers import (
    new_id, now_timestamp, parse_date, require_enum, require_int,
    require_string, err_validation, temporal_error,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, list_response
from serializers import serialize, get_or_404, bump_version

bp = Blueprint("residual_obligations", __name__)

REUSE_MARKETS = {
    "NETWORK_REBROADCAST", "SYNDICATION", "STREAMING", "FOREIGN", "HOME_VIDEO"
}


@bp.post("/payroll/residual-obligations")
def create_residual_obligation():
    require_roles({"ProductionAccountant"})
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object")

    engagement_id = require_string(body, "engagement_id")
    reuse_market = require_enum(body, "reuse_market", REUSE_MARKETS)
    window_start_raw = require_string(body, "window_start")
    window_end_raw = require_string(body, "window_end")
    reported_gross_receipts_cents = require_int(
        body, "reported_gross_receipts_cents", minimum=0
    )

    # ---- priority 3: FK existence ----
    engagement = get_or_404(db.engagements, engagement_id, "Engagement")

    # ---- priority 13: engagement ACTIVE or WRAPPED ----
    if engagement["status"] not in {"ACTIVE", "WRAPPED"}:
        raise ApiError(
            ERR_COMPLIANCE_STATE,
            "Residual create requires engagement status ACTIVE or WRAPPED",
            409,
        )

    # ---- priority 15: closed-interval window shape ----
    window_start = parse_date(window_start_raw, "window_start")
    window_end = parse_date(window_end_raw, "window_end")
    if window_end < window_start:
        raise temporal_error("window_end must be on or after window_start")

    # ---- priority 18: closed-interval window overlap for same engagement+market ----
    for other in db.residual_obligations.values():
        if other["engagement_id"] != engagement_id:
            continue
        if other["reuse_market"] != reuse_market:
            continue
        other_start = parse_date(other["window_start"], "window_start")
        other_end = parse_date(other["window_end"], "window_end")
        if other_start <= window_end and window_start <= other_end:
            raise ApiError(
                ERR_RESIDUAL_WINDOW_OVERLAP,
                "Residual window overlap for the same engagement + reuse_market",
                409,
            )

    # ---- priority 24: market base pct present ----
    agreement = get_or_404(
        db.union_agreements, engagement["union_agreement_id"], "UnionAgreement"
    )
    base_pct_map = agreement.get("residual_base_pct_by_market", {})
    if reuse_market not in base_pct_map:
        raise ApiError(
            ERR_MARKET_BASE_PCT_MISSING,
            f"reuse_market '{reuse_market}' has no base percentage in the agreement",
            422,
        )
    base_pct = base_pct_map[reuse_market]

    tier = find_tier(agreement, engagement["tier_code"])

    now = now_timestamp()
    window_sequence = assign_window_sequence(
        engagement_id, reuse_market, window_start_raw, now
    )
    provisional = residual_provisional_amount(tier, base_pct)

    record = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "engagement_id": engagement_id,
        "reuse_market": reuse_market,
        "window_start": window_start_raw,
        "window_end": window_end_raw,
        "reported_gross_receipts_cents": reported_gross_receipts_cents,
        "base_pct": base_pct,
        "window_sequence": window_sequence,
        "provisional_amount_cents": provisional,
        "final_amount_cents": 0,
        "status": "REPORTED",
    }
    db.residual_obligations[record["id"]] = record
    return success_object(serialize(record), 201)


@bp.get("/payroll/residual-obligations")
def list_residual_obligations():
    require_roles(ALL_ROLES)
    items = list(db.residual_obligations.values())
    engagement_id = request.args.get("engagement_id")
    if engagement_id is not None:
        items = [r for r in items if r["engagement_id"] == engagement_id]
    reuse_market = request.args.get("reuse_market")
    if reuse_market is not None:
        items = [r for r in items if r["reuse_market"] == reuse_market]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response([serialize(r) for r in items], request.args)


@bp.get("/payroll/residual-obligations/<obligation_id>")
def get_residual_obligation(obligation_id):
    require_roles(ALL_ROLES)
    obligation = get_or_404(db.residual_obligations, obligation_id, "ResidualObligation")
    return success_object(serialize(obligation), 200)


@bp.post("/payroll/residual-obligations/<obligation_id>/calculate")
def calculate_residual_obligation(obligation_id):
    require_roles({"PayrollClerk"})
    obligation = get_or_404(db.residual_obligations, obligation_id, "ResidualObligation")

    if obligation["status"] not in {"REPORTED", "DISPUTED"}:
        raise ApiError(
            ERR_RESIDUAL_INVALID_STATE,
            "Calculate requires status REPORTED or DISPUTED",
            409,
        )

    # Cross-entity gate: the engagement's agreement must be RATIFIED
    engagement = get_or_404(db.engagements, obligation["engagement_id"], "Engagement")
    agreement = get_or_404(
        db.union_agreements, engagement["union_agreement_id"], "UnionAgreement"
    )
    if agreement["status"] != "RATIFIED":
        raise ApiError(
            ERR_COMPLIANCE_STATE,
            "Residual calculate requires the governing agreement to be RATIFIED",
            409,
        )

    obligation["final_amount_cents"] = residual_final_amount(
        obligation["reported_gross_receipts_cents"],
        obligation["base_pct"],
        obligation["window_sequence"],
    )
    obligation["status"] = "CALCULATED"
    bump_version(obligation)
    return success_object(serialize(obligation), 200)


@bp.post("/payroll/residual-obligations/<obligation_id>/approve")
def approve_residual_obligation(obligation_id):
    require_roles({"PayrollSupervisor"})
    obligation = get_or_404(db.residual_obligations, obligation_id, "ResidualObligation")

    if obligation["status"] != "CALCULATED":
        raise ApiError(
            ERR_RESIDUAL_INVALID_STATE,
            "Approve requires status CALCULATED",
            409,
        )

    obligation["status"] = "APPROVED"
    bump_version(obligation)
    return success_object(serialize(obligation), 200)


@bp.post("/payroll/residual-obligations/<obligation_id>/dispute")
def dispute_residual_obligation(obligation_id):
    require_roles({"UnionAuditor"})
    obligation = get_or_404(db.residual_obligations, obligation_id, "ResidualObligation")

    if obligation["status"] != "APPROVED":
        raise ApiError(
            ERR_RESIDUAL_INVALID_STATE,
            "Dispute requires status APPROVED",
            409,
        )

    body = request.get_json(silent=True)
    dispute_reason = None
    if isinstance(body, dict):
        dispute_reason = body.get("dispute_reason")
    if not isinstance(dispute_reason, str) or dispute_reason == "":
        raise ApiError(ERR_VALIDATION, "dispute_reason is required", 400)

    obligation["status"] = "DISPUTED"
    bump_version(obligation)
    return success_object(serialize(obligation), 200)
