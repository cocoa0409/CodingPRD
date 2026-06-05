"""Claim lifecycle routes (PRD §3.2, §3.3, §3.6, §3.9). The FNOL state
machine, OCC-guarded transitions, and the disposition fork live here.
"""
from flask import Blueprint

import db
import serializers as S
from auth import authenticate, authorize
from errors import err
from helpers import (get_json_body, require_resource, require_fields,
                     require_int, optional_int, require_fault_pct,
                     require_enum, parse_pagination, paginate)
from response import success, list_success
from util import parse_iso
from services import calc
from services.lookups import (
    coverage_of_type, matched_coverage_for_claim, submitted_estimate,
    submitted_estimates, positive_total_loss_eval, has_positive_total_loss_eval,
    verifications_for_claim, pending_rentals, rental_coverage,
)

bp = Blueprint("claims", __name__)

ALL_ROLES = {"ClaimsSupervisor", "ClaimsAdjuster", "TotalLossAdjuster",
             "SubrogationSpecialist"}
LOSS_TYPES = {"COLLISION", "COMPREHENSIVE"}


# --------------------------------------------------------------------------
# OCC helper (PRD §2.7): expected_claim_version must match Claim.version.
# --------------------------------------------------------------------------
def _check_occ(body, claim_rec):
    require_fields(body, ["expected_claim_version"])
    expected = body["expected_claim_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err("ERR_INVALID_REQUEST", "expected_claim_version must be an integer")
    if expected != claim_rec["version"]:
        raise err("ERR_STALE_CLAIM_VERSION",
                  "expected_claim_version %s != current %s"
                  % (expected, claim_rec["version"]))


# --------------------------------------------------------------------------
# Create / read / list
# --------------------------------------------------------------------------
@bp.route("/claims", methods=["POST"])
def create_claim():
    principal = authenticate()
    authorize(principal, {"ClaimsAdjuster", "ClaimsSupervisor"})
    body = get_json_body()
    require_fields(body, ["policy_id", "loss_datetime", "loss_type",
                          "vehicle_acv_cents"])
    policy = require_resource(db.policies, body["policy_id"], "policy")
    loss_datetime = parse_iso(body["loss_datetime"])
    loss_type = require_enum(body, "loss_type", LOSS_TYPES)
    vehicle_acv_cents = require_int(body, "vehicle_acv_cents")
    insured_fault_pct = require_fault_pct(body, "insured_fault_pct", 0)
    salvage_value_cents = optional_int(body, "salvage_value_cents", 0)

    rec = {
        "policy_id": policy["id"],
        "assigned_adjuster_id": None,
        "loss_datetime": loss_datetime,
        "loss_type": loss_type,
        "vehicle_acv_cents": vehicle_acv_cents,
        "insured_fault_pct": insured_fault_pct,
        "status": "FNOL_SUBMITTED",
        "disposition": None,
        "settlement_cents": 0,
        "salvage_value_cents": salvage_value_cents,
        "total_disbursed_cents": 0,
    }
    db.insert(db.claims, rec)
    return success(S.claim(rec), status=201)


@bp.route("/claims/<cid>", methods=["GET"])
def get_claim(cid):
    principal = authenticate()
    authorize(principal, ALL_ROLES)
    rec = require_resource(db.claims, cid, "claim")
    return success(S.claim(rec), status=200)


@bp.route("/claims", methods=["GET"])
def list_claims():
    principal = authenticate()
    authorize(principal, ALL_ROLES)
    limit, offset = parse_pagination()
    from flask import request
    policy_id = request.args.get("policy_id")
    assigned_adjuster_id = request.args.get("assigned_adjuster_id")
    status = request.args.get("status")
    rows = list(db.claims.values())
    if policy_id is not None:
        rows = [r for r in rows if r["policy_id"] == policy_id]
    if assigned_adjuster_id is not None:
        rows = [r for r in rows if r["assigned_adjuster_id"] == assigned_adjuster_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_success([S.claim(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# verify-coverage (FNOL_SUBMITTED|REOPENED -> COVERAGE_VERIFIED|COVERAGE_DENIED)
# --------------------------------------------------------------------------
@bp.route("/claims/<cid>/verify-coverage", methods=["POST"])
def verify_coverage(cid):
    principal = authenticate()
    authorize(principal, {"ClaimsAdjuster"})
    claim = require_resource(db.claims, cid, "claim")
    if claim["status"] not in ("FNOL_SUBMITTED", "REOPENED"):
        raise err("ERR_INVALID_STATE",
                  "verify-coverage not allowed from %s" % claim["status"])

    policy = db.policies.get(claim["policy_id"])
    # Evaluate the three conditions; first failing one sets denial_reason.
    denial_reason = None
    if policy is None or policy["status"] != "ACTIVE":
        denial_reason = "POLICY_INACTIVE"
    elif not (policy["effective_date"] <= claim["loss_datetime"] < policy["expiration_date"]):
        denial_reason = "OUTSIDE_COVERAGE_WINDOW"
    elif coverage_of_type(policy["id"], claim["loss_type"]) is None:
        denial_reason = "NO_MATCHING_COVERAGE"

    if denial_reason is None:
        matched = coverage_of_type(policy["id"], claim["loss_type"])
        ver = {
            "claim_id": claim["id"],
            "matched_coverage_type": matched["coverage_type"],
            "outcome": "VERIFIED",
            "denial_reason": None,
            "_cleared": False,
        }
        db.insert(db.coverage_verifications, ver)
        claim["status"] = "COVERAGE_VERIFIED"
    else:
        ver = {
            "claim_id": claim["id"],
            "matched_coverage_type": None,
            "outcome": "DENIED",
            "denial_reason": denial_reason,
            "_cleared": False,
        }
        db.insert(db.coverage_verifications, ver)
        claim["status"] = "COVERAGE_DENIED"

    db.touch_no_version(claim)
    return success(S.claim(claim), status=200)


# --------------------------------------------------------------------------
# assign-adjuster (COVERAGE_VERIFIED -> UNDER_REVIEW), OCC-guarded
# --------------------------------------------------------------------------
@bp.route("/claims/<cid>/assign-adjuster", methods=["POST"])
def assign_adjuster(cid):
    principal = authenticate()
    authorize(principal, {"ClaimsSupervisor"})
    claim = require_resource(db.claims, cid, "claim")
    body = get_json_body()
    require_fields(body, ["adjuster_id", "expected_claim_version"])
    adjuster = require_resource(db.adjusters, body["adjuster_id"], "adjuster")

    if claim["status"] != "COVERAGE_VERIFIED":
        raise err("ERR_INVALID_STATE",
                  "assign-adjuster not allowed from %s" % claim["status"])
    _check_occ(body, claim)

    if not adjuster["active"]:
        raise err("ERR_INVALID_STATE", "adjuster is not active")
    if claim["assigned_adjuster_id"] is not None:
        raise err("ERR_INVALID_STATE", "claim already has an assigned adjuster")

    claim["assigned_adjuster_id"] = adjuster["id"]
    claim["status"] = "UNDER_REVIEW"
    db.touch(claim)  # version bump (workflow-named transition)
    return success(S.claim(claim), status=200)


# --------------------------------------------------------------------------
# decide-disposition (UNDER_REVIEW -> REPAIR_APPROVED | TOTAL_LOSS), OCC-guarded
# --------------------------------------------------------------------------
@bp.route("/claims/<cid>/decide-disposition", methods=["POST"])
def decide_disposition(cid):
    principal = authenticate()
    # Both roles are allowed at the route level; the branch enforces the
    # role-vs-decision pairing below.
    authorize(principal, {"ClaimsAdjuster", "TotalLossAdjuster"})
    claim = require_resource(db.claims, cid, "claim")
    body = get_json_body()
    require_fields(body, ["decision", "expected_claim_version"])
    decision = require_enum(body, "decision", {"REPAIR", "TOTAL_LOSS"})

    # Role must match the decision branch (RBAC §1.7: REPAIR is ClaimsAdjuster's
    # shared op, TOTAL_LOSS is TotalLossAdjuster's shared op).
    if decision == "REPAIR" and principal.role != "ClaimsAdjuster":
        raise err("ERR_FORBIDDEN_ROLE", "only ClaimsAdjuster may decide REPAIR")
    if decision == "TOTAL_LOSS" and principal.role != "TotalLossAdjuster":
        raise err("ERR_FORBIDDEN_ROLE", "only TotalLossAdjuster may decide TOTAL_LOSS")

    # State guard, then OCC, then business gates (PRD §3.6 ordering).
    if claim["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE",
                  "decide-disposition not allowed from %s" % claim["status"])
    _check_occ(body, claim)

    if decision == "REPAIR":
        return _decide_repair(claim)
    return _decide_total_loss(claim)


def _decide_repair(claim):
    # Exactly one SUBMITTED estimate and no is_total_loss=true evaluation.
    subs = submitted_estimates(claim["id"])
    if len(subs) != 1:
        raise err("ERR_NO_SUBMITTED_ESTIMATE",
                  "REPAIR requires exactly one SUBMITTED repair estimate")
    if has_positive_total_loss_eval(claim["id"]):
        raise err("ERR_NO_SUBMITTED_ESTIMATE",
                  "a total-loss evaluation exists for this claim")
    estimate = subs[0]
    matched = matched_coverage_for_claim(claim)
    if matched is None:
        raise err("ERR_INVALID_STATE", "no matched coverage for claim")

    settlement = calc.repair_path_settlement(
        estimate["repair_total_cents"], matched["deductible_cents"],
        matched["limit_cents"])
    claim["disposition"] = "REPAIR"
    claim["settlement_cents"] = settlement
    claim["status"] = "REPAIR_APPROVED"
    db.touch(claim)  # version bump
    return success(S.claim(claim), status=200)


def _decide_total_loss(claim):
    # Segregation of duties is checked before the not-a-total-loss check
    # (validations priority 7 before 12; PRD §3.6 "segregation before not-a-tl").
    eval_pos = positive_total_loss_eval(claim["id"])
    estimate = submitted_estimate(claim["id"])

    if eval_pos is not None and estimate is not None:
        if eval_pos["evaluated_by_adjuster_id"] == estimate["authored_by_adjuster_id"]:
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "evaluation author equals the submitted estimate author")
    if eval_pos is None:
        raise err("ERR_NOT_A_TOTAL_LOSS",
                  "no total-loss evaluation with is_total_loss=true")

    matched = matched_coverage_for_claim(claim)
    if matched is None:
        raise err("ERR_INVALID_STATE", "no matched coverage for claim")

    # Hop 1: disposition -> TOTAL_LOSS, recompute settlement.
    settlement = calc.total_loss_settlement(
        eval_pos["acv_cents"], claim["salvage_value_cents"],
        eval_pos["salvage_retained_by_insurer"],
        matched["deductible_cents"], matched["limit_cents"])
    claim["disposition"] = "TOTAL_LOSS"
    claim["settlement_cents"] = settlement
    claim["status"] = "TOTAL_LOSS"

    # Hop 2 (caused by Hop 1): recompute every PENDING rental with the
    # five-day-curtailed cap.
    for rental in pending_rentals(claim["id"]):
        _recompute_pending_rental(claim, rental)

    db.touch(claim)  # version bump
    return success(S.claim(claim), status=200)


def _recompute_pending_rental(claim, rental):
    cov = rental_coverage(claim["policy_id"])
    rmax = cov["rental_max_days"] if cov else 0
    daily_cap = cov["rental_daily_cap_cents"] if cov else 0
    requested = calc.rental_requested_days(rental["rental_start_date"],
                                           rental["rental_end_date"])
    days, cents = calc.rental_reimbursement(
        requested, rmax, daily_cap, rental["daily_rate_cents"],
        claim["disposition"])
    rental["reimbursable_days"] = days
    rental["reimbursement_cents"] = cents
    db.touch(rental)


# --------------------------------------------------------------------------
# settle (REPAIR_APPROVED|TOTAL_LOSS -> SETTLED), OCC-guarded
# --------------------------------------------------------------------------
@bp.route("/claims/<cid>/settle", methods=["POST"])
def settle_claim(cid):
    principal = authenticate()
    authorize(principal, {"ClaimsSupervisor"})
    claim = require_resource(db.claims, cid, "claim")
    body = get_json_body()
    require_fields(body, ["expected_claim_version"])

    if claim["status"] not in ("REPAIR_APPROVED", "TOTAL_LOSS"):
        raise err("ERR_INVALID_STATE", "settle not allowed from %s" % claim["status"])
    _check_occ(body, claim)

    if claim["settlement_cents"] <= 0:
        raise err("ERR_NO_SETTLEMENT_AMOUNT", "settlement_cents is not positive")

    disb = {
        "claim_id": claim["id"],
        "disbursement_type": "SETTLEMENT",
        "amount_cents": claim["settlement_cents"],
        "source_entity_id": claim["id"],
        "status": "APPROVED",
    }
    db.insert(db.disbursements, disb)
    calc.refresh_claim_ledger(claim)  # touch_no_version
    claim["status"] = "SETTLED"
    db.touch(claim)  # version bump
    return success(S.claim(claim), status=200)


# --------------------------------------------------------------------------
# close (SETTLED -> CLOSED)
# --------------------------------------------------------------------------
@bp.route("/claims/<cid>/close", methods=["POST"])
def close_claim(cid):
    principal = authenticate()
    authorize(principal, {"ClaimsSupervisor"})
    claim = require_resource(db.claims, cid, "claim")
    if claim["status"] != "SETTLED":
        raise err("ERR_INVALID_STATE", "close not allowed from %s" % claim["status"])

    open_sub = [s for s in db.subrogation_cases.values()
                if s["claim_id"] == claim["id"]
                and s["status"] in ("OPEN", "DEMAND_SENT", "NEGOTIATING")]
    if open_sub:
        raise err("ERR_INVALID_STATE", "open subrogation case prevents close")
    if pending_rentals(claim["id"]):
        raise err("ERR_INVALID_STATE", "pending rental reimbursement prevents close")

    claim["status"] = "CLOSED"
    db.touch_no_version(claim)
    return success(S.claim(claim), status=200)


# --------------------------------------------------------------------------
# reopen (COVERAGE_DENIED -> REOPENED)
# --------------------------------------------------------------------------
@bp.route("/claims/<cid>/reopen", methods=["POST"])
def reopen_claim(cid):
    principal = authenticate()
    authorize(principal, {"ClaimsSupervisor"})
    claim = require_resource(db.claims, cid, "claim")
    if claim["status"] != "COVERAGE_DENIED":
        raise err("ERR_INVALID_STATE", "reopen not allowed from %s" % claim["status"])

    # Clear prior CoverageVerification linkage so coverage can be re-verified.
    for v in verifications_for_claim(claim["id"]):
        v["_cleared"] = True
        db.touch_no_version(v)

    claim["status"] = "REOPENED"
    db.touch_no_version(claim)
    return success(S.claim(claim), status=200)


# --------------------------------------------------------------------------
# Computed ledger read
# --------------------------------------------------------------------------
@bp.route("/claims/<cid>/ledger", methods=["GET"])
def claim_ledger(cid):
    principal = authenticate()
    authorize(principal, {"ClaimsSupervisor", "ClaimsAdjuster", "SubrogationSpecialist"})
    claim = require_resource(db.claims, cid, "claim")
    net, count = calc.claim_ledger_balance(claim["id"])
    return success({"net_paid_cents": net, "disbursement_count": count}, status=200)


# --------------------------------------------------------------------------
# Reverse-reachability list endpoints under a claim
# --------------------------------------------------------------------------
@bp.route("/claims/<cid>/coverage-verifications", methods=["GET"])
def list_claim_verifications(cid):
    principal = authenticate()
    authorize(principal, {"ClaimsSupervisor", "ClaimsAdjuster"})
    require_resource(db.claims, cid, "claim")
    limit, offset = parse_pagination()
    rows = [v for v in db.coverage_verifications.values() if v["claim_id"] == cid]
    page, total = paginate(rows, limit, offset)
    return list_success([S.coverage_verification(r) for r in page], limit, offset, total)


@bp.route("/claims/<cid>/parties", methods=["GET"])
def list_claim_parties(cid):
    principal = authenticate()
    authorize(principal, {"ClaimsSupervisor", "ClaimsAdjuster", "SubrogationSpecialist"})
    require_resource(db.claims, cid, "claim")
    limit, offset = parse_pagination()
    rows = [p for p in db.claim_parties.values() if p["claim_id"] == cid]
    page, total = paginate(rows, limit, offset)
    return list_success([S.claim_party(r) for r in page], limit, offset, total)


@bp.route("/claims/<cid>/disbursements", methods=["GET"])
def list_claim_disbursements(cid):
    principal = authenticate()
    authorize(principal, {"ClaimsSupervisor", "ClaimsAdjuster", "SubrogationSpecialist"})
    require_resource(db.claims, cid, "claim")
    limit, offset = parse_pagination()
    rows = [d for d in db.disbursements.values() if d["claim_id"] == cid]
    page, total = paginate(rows, limit, offset)
    return list_success([S.disbursement(r) for r in page], limit, offset, total)
