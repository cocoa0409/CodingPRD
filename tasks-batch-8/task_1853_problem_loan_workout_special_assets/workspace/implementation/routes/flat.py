"""Flat convenience GET routes (PRD §2.7 reverse reachability)."""
from flask import Blueprint, request

from auth import (
    ALL_ROLES, ROLE_APPRAISAL_DESK, ROLE_CREDIT_COMMITTEE, ROLE_LEGAL_COUNSEL,
    ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST, ROLE_SPECIAL_ASSETS_MANAGER,
    ROLE_SYSTEM_ADMIN, ROLE_WORKOUT_OFFICER, require_roles,
)
from db import STORE
from errors import ApiError, ERR_NOT_FOUND
from response import ok, paginate
from services import (
    appraisal_out, case_out, charge_off_out, collateral_out,
    exit_decision_out, get_appraisal, get_case, get_charge_off,
    get_collateral, get_exit_decision, get_impairment, get_plan,
    get_proposal, get_recovery, get_referral, impairment_out, plan_out,
    proposal_out, recovery_out, referral_out, sorted_rows,
)

bp = Blueprint("flat", __name__)

PLAN_READERS = (
    ROLE_WORKOUT_OFFICER, ROLE_SPECIAL_ASSETS_MANAGER, ROLE_CREDIT_COMMITTEE,
    ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST, ROLE_SYSTEM_ADMIN,
)
ITEM_READERS = (
    ROLE_WORKOUT_OFFICER, ROLE_SPECIAL_ASSETS_MANAGER, ROLE_APPRAISAL_DESK,
    ROLE_LEGAL_COUNSEL, ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST,
    ROLE_SYSTEM_ADMIN,
)
APPRAISAL_READERS = (
    ROLE_WORKOUT_OFFICER, ROLE_SPECIAL_ASSETS_MANAGER, ROLE_APPRAISAL_DESK,
    ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST, ROLE_SYSTEM_ADMIN,
)
REFERRAL_READERS = (
    ROLE_WORKOUT_OFFICER, ROLE_SPECIAL_ASSETS_MANAGER, ROLE_LEGAL_COUNSEL,
    ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST, ROLE_SYSTEM_ADMIN,
)
RECOVERY_READERS = (
    ROLE_WORKOUT_OFFICER, ROLE_SPECIAL_ASSETS_MANAGER, ROLE_CREDIT_COMMITTEE,
    ROLE_LEGAL_COUNSEL, ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST,
    ROLE_SYSTEM_ADMIN,
)


def _fetch(table_getter, resource_id, label):
    entity = table_getter(resource_id)
    if entity is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"{label} not found")
    return entity


# --- workout cases ---
@bp.route("/workout-cases/<caseId>", methods=["GET"])
def flat_get_case(caseId):
    require_roles(*ALL_ROLES)
    return ok(case_out(_fetch(get_case, caseId, "Workout case")))


@bp.route("/workout-cases", methods=["GET"])
def flat_list_cases():
    require_roles(*ALL_ROLES)
    rows = STORE["cases"].values()
    loan_id = request.args.get("loan_id")
    if loan_id is not None:
        rows = [c for c in rows if c["loan_id"] == loan_id]
    return paginate([case_out(c) for c in sorted_rows(rows)])


# --- action plans ---
@bp.route("/action-plans/<planId>", methods=["GET"])
def flat_get_plan(planId):
    require_roles(*PLAN_READERS)
    return ok(plan_out(_fetch(get_plan, planId, "Action plan")))


@bp.route("/action-plans", methods=["GET"])
def flat_list_plans():
    require_roles(*PLAN_READERS)
    rows = STORE["plans"].values()
    case_id = request.args.get("case_id")
    supersedes = request.args.get("supersedes_plan_id")
    if case_id is not None:
        rows = [p for p in rows if p["case_id"] == case_id]
    if supersedes is not None:
        rows = [p for p in rows if p["supersedes_plan_id"] == supersedes]
    return paginate([plan_out(p) for p in sorted_rows(rows)])


# --- proposals ---
@bp.route("/proposals/<proposalId>", methods=["GET"])
def flat_get_proposal(proposalId):
    require_roles(*PLAN_READERS)
    return ok(proposal_out(_fetch(get_proposal, proposalId, "Proposal")))


@bp.route("/proposals", methods=["GET"])
def flat_list_proposals():
    require_roles(*PLAN_READERS)
    rows = STORE["proposals"].values()
    case_id = request.args.get("case_id")
    if case_id is not None:
        rows = [p for p in rows if p["case_id"] == case_id]
    return paginate([proposal_out(p) for p in sorted_rows(rows)])


# --- collateral items ---
@bp.route("/collateral-items/<collateralId>", methods=["GET"])
def flat_get_collateral(collateralId):
    require_roles(*ITEM_READERS)
    return ok(collateral_out(_fetch(get_collateral, collateralId, "Collateral item")))


@bp.route("/collateral-items", methods=["GET"])
def flat_list_collateral():
    require_roles(*ITEM_READERS)
    rows = STORE["collateral"].values()
    loan_id = request.args.get("loan_id")
    if loan_id is not None:
        rows = [c for c in rows if c["loan_id"] == loan_id]
    return paginate([collateral_out(c) for c in sorted_rows(rows)])


# --- appraisals ---
@bp.route("/appraisals/<appraisalId>", methods=["GET"])
def flat_get_appraisal(appraisalId):
    require_roles(*APPRAISAL_READERS)
    return ok(appraisal_out(_fetch(get_appraisal, appraisalId, "Appraisal")))


@bp.route("/appraisals", methods=["GET"])
def flat_list_appraisals():
    require_roles(*APPRAISAL_READERS)
    rows = STORE["appraisals"].values()
    collateral_id = request.args.get("collateral_id")
    if collateral_id is not None:
        rows = [a for a in rows if a["collateral_id"] == collateral_id]
    return paginate([appraisal_out(a) for a in sorted_rows(rows)])


# --- impairments ---
@bp.route("/impairments/<assessmentId>", methods=["GET"])
def flat_get_impairment(assessmentId):
    require_roles(*PLAN_READERS)
    return ok(impairment_out(_fetch(get_impairment, assessmentId, "Impairment")))


@bp.route("/impairments", methods=["GET"])
def flat_list_impairments():
    require_roles(*PLAN_READERS)
    rows = STORE["impairments"].values()
    case_id = request.args.get("case_id")
    if case_id is not None:
        rows = [a for a in rows if a["case_id"] == case_id]
    return paginate([impairment_out(a) for a in sorted_rows(rows)])


# --- legal referrals ---
@bp.route("/legal-referrals/<referralId>", methods=["GET"])
def flat_get_referral(referralId):
    require_roles(*REFERRAL_READERS)
    return ok(referral_out(_fetch(get_referral, referralId, "Legal referral")))


@bp.route("/legal-referrals", methods=["GET"])
def flat_list_referrals():
    require_roles(*REFERRAL_READERS)
    rows = STORE["referrals"].values()
    case_id = request.args.get("case_id")
    if case_id is not None:
        rows = [r for r in rows if r["case_id"] == case_id]
    return paginate([referral_out(r) for r in sorted_rows(rows)])


# --- charge-offs ---
@bp.route("/charge-offs/<chargeOffId>", methods=["GET"])
def flat_get_charge_off(chargeOffId):
    require_roles(*PLAN_READERS)
    return ok(charge_off_out(_fetch(get_charge_off, chargeOffId, "Charge-off")))


@bp.route("/charge-offs", methods=["GET"])
def flat_list_charge_offs():
    require_roles(*PLAN_READERS)
    rows = STORE["charge_offs"].values()
    case_id = request.args.get("case_id")
    if case_id is not None:
        rows = [e for e in rows if e["case_id"] == case_id]
    return paginate([charge_off_out(e) for e in sorted_rows(rows)])


# --- recoveries ---
@bp.route("/recoveries/<recoveryId>", methods=["GET"])
def flat_get_recovery(recoveryId):
    require_roles(*RECOVERY_READERS)
    return ok(recovery_out(_fetch(get_recovery, recoveryId, "Recovery")))


@bp.route("/recoveries", methods=["GET"])
def flat_list_recoveries():
    require_roles(*RECOVERY_READERS)
    rows = STORE["recoveries"].values()
    case_id = request.args.get("case_id")
    if case_id is not None:
        rows = [e for e in rows if e["case_id"] == case_id]
    return paginate([recovery_out(e) for e in sorted_rows(rows)])


# --- exit decisions ---
@bp.route("/exit-decisions/<decisionId>", methods=["GET"])
def flat_get_exit_decision(decisionId):
    require_roles(*PLAN_READERS)
    return ok(
        exit_decision_out(_fetch(get_exit_decision, decisionId, "Exit decision"))
    )


@bp.route("/exit-decisions", methods=["GET"])
def flat_list_exit_decisions():
    require_roles(*PLAN_READERS)
    rows = STORE["exit_decisions"].values()
    case_id = request.args.get("case_id")
    if case_id is not None:
        rows = [d for d in rows if d["case_id"] == case_id]
    return paginate([exit_decision_out(d) for d in sorted_rows(rows)])
