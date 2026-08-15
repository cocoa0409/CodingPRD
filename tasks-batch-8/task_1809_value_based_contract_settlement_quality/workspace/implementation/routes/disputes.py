"""SettlementDispute endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_DISPUTE_NOT_EXPIRABLE,
    ERR_DISPUTE_RESOLUTION_WINDOW_ELAPSED,
    ERR_DISPUTE_WINDOW_CLOSED,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SETTLEMENT_NOT_FINAL,
)
from middleware import ALL_ROLES, check_group_scope, require_roles
from response import success_list, success_object
from services import calculations as calc
from services import engine
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    reject_unknown_fields,
    require_enum,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("disputes", __name__)

REASON_CODES = {
    "ATTRIBUTION_ERROR",
    "CLAIMS_MISSING",
    "RISK_SCORE_ERROR",
    "QUALITY_DATA_ERROR",
    "BENCHMARK_ERROR",
}


def _group_id_for_settlement(settlement: dict) -> str | None:
    year = db.performance_years.get(settlement["performance_year_id"])
    if year is None:
        return None
    contract = db.contracts.get(year["contract_id"])
    return contract["practice_group_id"] if contract else None


def _group_id_for_dispute(dispute: dict) -> str | None:
    settlement = db.settlements.get(dispute["settlement_id"])
    return _group_id_for_settlement(settlement) if settlement else None


def _get_dispute_or_404(dispute_id: str) -> dict:
    dispute = db.settlement_disputes.get(dispute_id)
    if dispute is None:
        raise_err(ERR_NOT_FOUND, "SettlementDispute id does not exist")
    return dispute


def _return_settlement_to_finalized(settlement: dict) -> None:
    """DISPUTED -> FINALIZED with finalized_on unchanged (the original dispute
    window anchor is preserved)."""
    if settlement["settlement_status"] == "DISPUTED":
        db.apply_updates(settlement, {"settlement_status": "FINALIZED"})


@bp.route("/vbc/settlements/<settlement_id>/disputes", methods=["POST"])
@require_roles("PracticeGroupRep")
def create_dispute(settlement_id: str, _user_id: str, _role: str):
    # Priority 3: path id.
    settlement = db.settlements.get(settlement_id)
    if settlement is None:
        raise_err(ERR_NOT_FOUND, "Settlement id does not exist")
    # Priority 4: PracticeGroupRep scope — caller's group must own the contract.
    check_group_scope(_user_id, _role, _group_id_for_settlement(settlement))
    # Priority 5: shape.
    body = get_json_body()
    reject_unknown_fields(body, {"dispute_ref", "reason_code", "claimed_adjustment_cents"})
    dispute_ref = require_string(body, "dispute_ref")
    reason_code = require_enum(body, "reason_code", REASON_CODES)
    claimed_adjustment_cents = require_int(body, "claimed_adjustment_cents")
    # Priority 6 (state): settlement must be FINALIZED.
    if settlement["settlement_status"] != "FINALIZED":
        raise_err(ERR_SETTLEMENT_NOT_FINAL, "Disputes can only be filed on a FINALIZED settlement")
    # Priority 8 (temporal): filing within finalized_on + DISPUTE_WINDOW_DAYS.
    window_end = db.add_days(db.parse_date(settlement["finalized_on"]), calc.DISPUTE_WINDOW_DAYS)
    if db.clock_date() > window_end:
        raise_err(ERR_DISPUTE_WINDOW_CLOSED, "Dispute filing window has closed")
    # Priority 12 (fiscal): claimed adjustment strictly positive.
    if claimed_adjustment_cents <= 0:
        raise_err(ERR_INVALID_AMOUNT, "claimed_adjustment_cents must be > 0")

    dispute = {
        "settlement_id": settlement_id,
        "dispute_ref": dispute_ref,
        "reason_code": reason_code,
        "claimed_adjustment_cents": claimed_adjustment_cents,
        "filed_on": db.clock_date_iso(),
        "review_started_on": None,
        "resolved_on": None,
        "resolved_by_user_id": None,
        "resolution_outcome": None,
        "dispute_status": "FILED",
    }
    db.stamp_new(dispute)
    db.settlement_disputes[dispute["id"]] = dispute
    # Filing transitions the settlement FINALIZED -> DISPUTED.
    db.apply_updates(settlement, {"settlement_status": "DISPUTED"})
    return success_object(dispute, 201)


@bp.route("/vbc/settlement-disputes", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_disputes(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.settlement_disputes.values()))
    items = apply_filters(items, ["settlement_id", "dispute_status"])
    if _role == "PracticeGroupRep":
        items = [d for d in items if _group_id_for_dispute(d) == _user_id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/vbc/settlement-disputes/<dispute_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_dispute(dispute_id: str, _user_id: str, _role: str):
    dispute = _get_dispute_or_404(dispute_id)
    check_group_scope(_user_id, _role, _group_id_for_dispute(dispute))
    return success_object(dispute)


@bp.route("/vbc/settlement-disputes/<dispute_id>/begin-review", methods=["POST"])
@require_roles("DisputeAdjudicator")
def begin_review(dispute_id: str, _user_id: str, _role: str):
    dispute = _get_dispute_or_404(dispute_id)
    if dispute["dispute_status"] != "FILED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a FILED dispute can begin review")
    dispute["dispute_status"] = "UNDER_REVIEW"
    dispute["review_started_on"] = db.clock_date_iso()
    db.touch(dispute)
    return success_object(dispute)


@bp.route("/vbc/settlement-disputes/<dispute_id>/resolve", methods=["POST"])
@require_roles("DisputeAdjudicator")
def resolve_dispute(dispute_id: str, _user_id: str, _role: str):
    dispute = _get_dispute_or_404(dispute_id)
    # Priority 5: shape.
    body = get_json_body()
    reject_unknown_fields(body, {"outcome"})
    outcome = require_enum(body, "outcome", {"UPHELD", "OVERRULED"})
    # Priority 6 (state): must be UNDER_REVIEW.
    if dispute["dispute_status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an UNDER_REVIEW dispute can be resolved")
    settlement = db.settlements[dispute["settlement_id"]]
    # Priority 7 (segregation of duties) before priority 8 (temporal window).
    if _user_id == settlement["finalized_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "The settlement's finalizer may not resolve its dispute")
    resolution_end = db.add_days(db.parse_date(dispute["filed_on"]), calc.DISPUTE_RESOLUTION_DAYS)
    if db.clock_date() > resolution_end:
        raise_err(ERR_DISPUTE_RESOLUTION_WINDOW_ELAPSED, "Dispute resolution window has elapsed")

    dispute["dispute_status"] = outcome
    dispute["resolved_on"] = db.clock_date_iso()
    dispute["resolved_by_user_id"] = _user_id
    dispute["resolution_outcome"] = outcome
    db.touch(dispute)

    if outcome == "UPHELD":
        # Settlement DISPUTED -> RECALCULATING -> PROVISIONAL in the same
        # request: full recompute from current (corrected) data, seq unchanged,
        # needs_recompute cleared. RECALCULATING is transient.
        engine.recompute_settlement_fields(settlement, recompute_year_cost=True)
        settlement["needs_recompute"] = False
        settlement["settlement_status"] = "PROVISIONAL"
        db.touch(settlement)
    else:
        # OVERRULED: settlement returns to FINALIZED with amounts unchanged.
        _return_settlement_to_finalized(settlement)
    return success_object(dispute)


@bp.route("/vbc/settlement-disputes/<dispute_id>/withdraw", methods=["POST"])
@require_roles("PracticeGroupRep")
def withdraw_dispute(dispute_id: str, _user_id: str, _role: str):
    dispute = _get_dispute_or_404(dispute_id)
    # Priority 4: scope — only the owning group may withdraw.
    check_group_scope(_user_id, _role, _group_id_for_dispute(dispute))
    if dispute["dispute_status"] not in ("FILED", "UNDER_REVIEW"):
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a FILED or UNDER_REVIEW dispute can be withdrawn")
    dispute["dispute_status"] = "WITHDRAWN"
    db.touch(dispute)
    settlement = db.settlements[dispute["settlement_id"]]
    _return_settlement_to_finalized(settlement)
    return success_object(dispute)


@bp.route("/vbc/settlement-disputes/<dispute_id>/expire", methods=["POST"])
@require_roles("DisputeAdjudicator")
def expire_dispute(dispute_id: str, _user_id: str, _role: str):
    dispute = _get_dispute_or_404(dispute_id)
    if dispute["dispute_status"] not in ("FILED", "UNDER_REVIEW"):
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a FILED or UNDER_REVIEW dispute can be expired")
    resolution_end = db.add_days(db.parse_date(dispute["filed_on"]), calc.DISPUTE_RESOLUTION_DAYS)
    if db.clock_date() <= resolution_end:
        raise_err(ERR_DISPUTE_NOT_EXPIRABLE, "Dispute resolution window has not elapsed")
    dispute["dispute_status"] = "EXPIRED"
    db.touch(dispute)
    settlement = db.settlements[dispute["settlement_id"]]
    _return_settlement_to_finalized(settlement)
    return success_object(dispute)
