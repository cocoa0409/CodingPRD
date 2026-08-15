"""Settlements, distribution lines, and reconciliation adjustments."""
from flask import Blueprint, request

import db
from errors import (ApiError, not_found, ERR_STALE_VERSION,
                    ERR_PERIOD_NOT_LOCKED, ERR_NO_ACTIVE_BENCHMARK,
                    ERR_UNADJUDICATED_CLAIMS_EXIST,
                    ERR_SETTLEMENT_ALREADY_FINAL, ERR_SETTLEMENT_NOT_PROPOSED,
                    ERR_SETTLEMENT_NOT_FINAL, ERR_QUALITY_SCORES_INCOMPLETE,
                    ERR_PENDING_REVIEWS_EXIST, ERR_DISTRIBUTION_RUN_EXISTS,
                    ERR_NO_DISTRIBUTABLE_POOL, ERR_DISTRIBUTION_INVALID_STATE,
                    ERR_SEGREGATION_OF_DUTIES, ERR_ADJUSTMENT_NOT_POSTED,
                    ERR_UNAUTHORIZED)
from middleware import (require_roles, ROLE_ACO_ADMIN, ROLE_ACTUARY,
                        ROLE_APPROVER, ROLE_PR, ROLE_APPEALS)
from response import success, list_success
from serializers import settlement_out, distribution_line_out, adjustment_out
from services import calc
from validate import get_json_body, validate_body

bp = Blueprint("settlements", __name__)

SETTLEMENT_SPEC = {
    "expected_agreement_period_version": {"type": "int", "required": True},
}

REOPEN_SPEC = {
    "reason": {"type": "string", "required": False},
}

ADJUSTMENT_SPEC = {
    "direction": {"type": "enum", "enum": ["CREDIT", "DEBIT"], "required": True},
    "amount_cents": {"type": "int", "required": True, "min": 1},
    "reason_code": {"type": "string", "required": True},
    "appeal_id": {"type": "string", "required": False},
}

SETTLEMENT_READ_ROLES = [ROLE_ACO_ADMIN, "ClaimsProcessor", "QualityReporter",
                         "QualityAuditor", ROLE_ACTUARY, ROLE_APPROVER,
                         "MedicalReviewOfficer", ROLE_APPEALS, ROLE_PR]
LINE_ROLES = [ROLE_ACO_ADMIN, ROLE_ACTUARY, ROLE_APPROVER, ROLE_PR]
ADJUSTMENT_READ_ROLES = [ROLE_ACO_ADMIN, ROLE_ACTUARY, ROLE_APPEALS]


def _get_settlement_or_404(settlement_id):
    settlement = db.settlements.get(settlement_id)
    if settlement is None:
        raise not_found("Settlement not found")
    return settlement


@bp.post("/aco/agreement-periods/<period_id>/settlements")
def create_settlement(period_id):
    require_roles([ROLE_ACTUARY])
    body = validate_body(get_json_body(), SETTLEMENT_SPEC)
    period = db.periods.get(period_id)
    if period is None:
        raise not_found("Agreement period not found")
    # OCC (priority 5) precedes period posture (priority 6).
    if body["expected_agreement_period_version"] != period["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_agreement_period_version does not match the "
                       "period's current version")
    if period["status"] != "ASSIGNMENT_LOCKED":
        raise ApiError(ERR_PERIOD_NOT_LOCKED, 409,
                       "Settlement computation requires an ASSIGNMENT_LOCKED period")
    # Cross-entity prerequisites (priority 12). ALREADY_FINAL is checked first:
    # finalization pins the referenced benchmark LOCKED, so a period holding a
    # FINAL settlement typically has no ACTIVE FINAL benchmark; checking the
    # benchmark first would mask ERR_SETTLEMENT_ALREADY_FINAL in that state.
    if any(s["agreement_period_id"] == period["id"]
           and s["status"] in ("FINAL", "SETTLED")
           for s in db.settlements.values()):
        raise ApiError(ERR_SETTLEMENT_ALREADY_FINAL, 409,
                       "A FINAL or SETTLED settlement already exists for this period")
    benchmark = calc.active_benchmark(period["id"], "FINAL")
    if benchmark is None:
        raise ApiError(ERR_NO_ACTIVE_BENCHMARK, 409,
                       "No ACTIVE FINAL-variant benchmark exists for this period")
    if any(c["agreement_period_id"] == period["id"] and c["status"] == "RECEIVED"
           for c in db.claims.values()):
        raise ApiError(ERR_UNADJUDICATED_CLAIMS_EXIST, 409,
                       "Claims of the period remain in RECEIVED")

    computed = calc.compute_settlement_fields(period, benchmark)
    settlement = db.stamp_new({
        "id": db.new_id(),
        "agreement_period_id": period["id"],
        "benchmark_id": computed["benchmark_id"],
        "expenditure_total_cents": computed["expenditure_total_cents"],
        "gross_savings_cents": computed["gross_savings_cents"],
        "msr_threshold_cents": computed["msr_threshold_cents"],
        "quality_score_snapshot": computed["quality_score_snapshot"],
        "quality_multiplier_snapshot": computed["quality_multiplier_snapshot"],
        "shared_savings_pre_sequestration_cents":
            computed["shared_savings_pre_sequestration_cents"],
        "sequestration_levy_cents": computed["sequestration_levy_cents"],
        "net_shared_savings_cents": computed["net_shared_savings_cents"],
        "shared_loss_cents": computed["shared_loss_cents"],
        "distributable_pool_cents": computed["distributable_pool_cents"],
        "reconciliation_balance_cents": 0,
        "last_distribution_run_by_user_id": None,
        "finalized_at_dt": None,
        "status": "PROPOSED",
    })
    db.settlements[settlement["id"]] = settlement
    # Supersede any prior live (PROPOSED / STALE / REOPENED) settlement.
    for existing in db.settlements.values():
        if (existing["agreement_period_id"] == period["id"]
                and existing["id"] != settlement["id"]
                and existing["status"] in ("PROPOSED", "STALE", "REOPENED")):
            existing["status"] = "SUPERSEDED"
            db.bump(existing)
    db.bump(period)
    return success(settlement_out(settlement), 201)


@bp.get("/aco/settlements/<settlement_id>")
def get_settlement(settlement_id):
    require_roles(SETTLEMENT_READ_ROLES)
    return success(settlement_out(_get_settlement_or_404(settlement_id)))


@bp.get("/aco/settlements")
def list_settlements():
    require_roles(SETTLEMENT_READ_ROLES)
    items = list(db.settlements.values())
    for param in ("agreement_period_id", "benchmark_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [s for s in items if s[param] == value]
    items.sort(key=lambda s: s["created_at"])
    return list_success([settlement_out(s) for s in items])


@bp.post("/aco/settlements/<settlement_id>/finalize")
def finalize_settlement(settlement_id):
    require_roles([ROLE_ACTUARY])
    get_json_body()
    settlement = _get_settlement_or_404(settlement_id)
    if settlement["status"] not in ("PROPOSED", "REOPENED"):
        raise ApiError(ERR_SETTLEMENT_NOT_PROPOSED, 409,
                       "Finalize requires the settlement to be PROPOSED or REOPENED")
    period_id = settlement["agreement_period_id"]
    if any(s["agreement_period_id"] == period_id
           and s["status"] in ("REPORTED", "REJECTED")
           for s in db.quality_scores.values()):
        raise ApiError(ERR_QUALITY_SCORES_INCOMPLETE, 409,
                       "Quality scores remain in REPORTED or REJECTED")
    if any(r["agreement_period_id"] == period_id and r["status"] == "FLAGGED"
           for r in db.high_cost_reviews.values()):
        raise ApiError(ERR_PENDING_REVIEWS_EXIST, 409,
                       "High-cost reviews remain FLAGGED")
    # Version-pin the referenced benchmark so the settled basis cannot be
    # superseded out from under the settlement.
    benchmark = db.benchmarks.get(settlement["benchmark_id"])
    if benchmark is not None and benchmark["status"] == "ACTIVE":
        benchmark["status"] = "LOCKED"
        db.bump(benchmark)
    settlement["finalized_at_dt"] = db.logical_now()
    settlement["status"] = "FINAL"
    db.bump(settlement)
    # A zero-pool settlement can never spawn a distribution run, so
    # finalization continues straight through to SETTLED.
    if settlement["distributable_pool_cents"] == 0:
        settlement["status"] = "SETTLED"
        calc.bubble_period_settled(period_id)
    return success(settlement_out(settlement))


@bp.post("/aco/settlements/<settlement_id>/reopen")
def reopen_settlement(settlement_id):
    require_roles([ROLE_ACTUARY])
    validate_body(get_json_body(), REOPEN_SPEC)
    settlement = _get_settlement_or_404(settlement_id)
    if settlement["status"] != "FINAL":
        raise ApiError(ERR_SETTLEMENT_NOT_FINAL, 409,
                       "Reopen requires the settlement to be FINAL")
    calc.reopen_settlement(settlement)
    return success(settlement_out(settlement))


@bp.post("/aco/settlements/<settlement_id>/distribution-runs")
def distribution_run(settlement_id):
    uid, _ = require_roles([ROLE_ACTUARY])
    get_json_body()
    settlement = _get_settlement_or_404(settlement_id)
    if settlement["status"] != "FINAL":
        raise ApiError(ERR_SETTLEMENT_NOT_FINAL, 409,
                       "Distribution runs require a FINAL settlement")
    # One live run at a time (priority 10) precedes the pool check (priority 13).
    if any(l["settlement_id"] == settlement["id"] and l["status"] != "VOIDED"
           for l in db.distribution_lines.values()):
        raise ApiError(ERR_DISTRIBUTION_RUN_EXISTS, 409,
                       "Non-VOIDED distribution lines already exist")
    pool = settlement["distributable_pool_cents"]
    if pool <= 0:
        raise ApiError(ERR_NO_DISTRIBUTABLE_POOL, 422,
                       "distributable_pool_cents must be positive")
    allocations = calc.waterfall_allocations(pool, settlement["agreement_period_id"])
    allocated_total = 0
    for participant, amount in allocations:
        line = db.stamp_new({
            "id": db.new_id(),
            "settlement_id": settlement["id"],
            "participant_id": participant["id"],
            "amount_cents": amount,
            "status": "PENDING",
        })
        db.distribution_lines[line["id"]] = line
        allocated_total += amount
    settlement["last_distribution_run_by_user_id"] = uid
    db.bump(settlement)
    return success({
        "created_count": len(allocations),
        "allocated_total_cents": allocated_total,
        "settlement_id": settlement["id"],
    }, 201)


# ---------------------------------------------------------------------------
# Distribution lines
# ---------------------------------------------------------------------------
def _get_line_or_404(line_id):
    line = db.distribution_lines.get(line_id)
    if line is None:
        raise not_found("Distribution line not found")
    return line


@bp.get("/aco/distribution-lines/<line_id>")
def get_line(line_id):
    uid, role = require_roles(LINE_ROLES)
    line = _get_line_or_404(line_id)
    # ParticipantRepresentative sees only their own participant's lines.
    if role == ROLE_PR and line["participant_id"] != uid:
        raise ApiError(ERR_UNAUTHORIZED, 403,
                       "Distribution line belongs to another participant")
    return success(distribution_line_out(line))


@bp.get("/aco/distribution-lines")
def list_lines():
    uid, role = require_roles(LINE_ROLES)
    items = list(db.distribution_lines.values())
    for param in ("settlement_id", "participant_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [l for l in items if l[param] == value]
    if role == ROLE_PR:
        items = [l for l in items if l["participant_id"] == uid]
    # Sorted amount_cents DESC, ties created_at ASC.
    items.sort(key=lambda l: (-l["amount_cents"], l["created_at"]))
    return list_success([distribution_line_out(l) for l in items])


@bp.post("/aco/distribution-lines/<line_id>/approve")
def approve_line(line_id):
    uid, _ = require_roles([ROLE_APPROVER])
    get_json_body()
    line = _get_line_or_404(line_id)
    # Entity state (priority 7) precedes segregation of duties (priority 8).
    if line["status"] != "PENDING":
        raise ApiError(ERR_DISTRIBUTION_INVALID_STATE, 409,
                       "Approve requires the line to be PENDING")
    settlement = db.settlements[line["settlement_id"]]
    if uid == settlement["last_distribution_run_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "Approver must differ from the distribution runner")
    line["status"] = "APPROVED"
    db.bump(line)
    return success(distribution_line_out(line))


@bp.post("/aco/distribution-lines/<line_id>/pay")
def pay_line(line_id):
    require_roles([ROLE_APPROVER])
    get_json_body()
    line = _get_line_or_404(line_id)
    if line["status"] != "APPROVED":
        raise ApiError(ERR_DISTRIBUTION_INVALID_STATE, 409,
                       "Pay requires the line to be APPROVED")
    line["status"] = "PAID"
    db.bump(line)
    settlement = db.settlements[line["settlement_id"]]
    calc.maybe_settle_from_lines(settlement)
    return success(distribution_line_out(line))


# ---------------------------------------------------------------------------
# Reconciliation adjustments
# ---------------------------------------------------------------------------
@bp.post("/aco/settlements/<settlement_id>/reconciliation-adjustments")
def create_adjustment(settlement_id):
    require_roles([ROLE_ACTUARY])
    body = validate_body(get_json_body(), ADJUSTMENT_SPEC)
    settlement = _get_settlement_or_404(settlement_id)
    appeal_id = body.get("appeal_id")
    if appeal_id is not None and appeal_id not in db.appeals:
        raise not_found("Appeal not found")
    # Adjustments post against FINAL / SETTLED / REOPENED settlements only.
    if settlement["status"] not in ("FINAL", "SETTLED", "REOPENED"):
        raise ApiError(ERR_SETTLEMENT_NOT_FINAL, 409,
                       "Adjustments require a FINAL, SETTLED, or REOPENED settlement")
    adjustment = db.stamp_new({
        "id": db.new_id(),
        "settlement_id": settlement["id"],
        "appeal_id": appeal_id,
        "direction": body["direction"],
        "amount_cents": body["amount_cents"],
        "reason_code": body["reason_code"],
        "status": "POSTED",
    })
    db.adjustments[adjustment["id"]] = adjustment
    calc.recompute_reconciliation_balance(settlement)
    return success(adjustment_out(adjustment), 201)


@bp.get("/aco/reconciliation-adjustments/<adjustment_id>")
def get_adjustment(adjustment_id):
    require_roles(ADJUSTMENT_READ_ROLES)
    adjustment = db.adjustments.get(adjustment_id)
    if adjustment is None:
        raise not_found("Reconciliation adjustment not found")
    return success(adjustment_out(adjustment))


@bp.get("/aco/reconciliation-adjustments")
def list_adjustments():
    require_roles(ADJUSTMENT_READ_ROLES)
    items = list(db.adjustments.values())
    for param in ("settlement_id", "appeal_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [a for a in items if a[param] == value]
    items.sort(key=lambda a: a["created_at"])
    return list_success([adjustment_out(a) for a in items])


@bp.post("/aco/reconciliation-adjustments/<adjustment_id>/reverse")
def reverse_adjustment(adjustment_id):
    require_roles([ROLE_ACTUARY])
    get_json_body()
    adjustment = db.adjustments.get(adjustment_id)
    if adjustment is None:
        raise not_found("Reconciliation adjustment not found")
    if adjustment["status"] != "POSTED":
        raise ApiError(ERR_ADJUSTMENT_NOT_POSTED, 409,
                       "Reverse requires the adjustment to be POSTED")
    adjustment["status"] = "REVERSED"
    db.bump(adjustment)
    calc.recompute_reconciliation_balance(db.settlements[adjustment["settlement_id"]])
    return success(adjustment_out(adjustment))
