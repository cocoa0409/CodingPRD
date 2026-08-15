"""InvestmentProposal endpoints: draft, recommend, IC approve/reject, withdraw."""

from flask import Blueprint, request

from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_REF_NOT_FOUND, ERR_INVALID_STATE,
    ERR_POSTURE_GATED, ERR_VEHICLE_NOT_APPROVED, ERR_MANAGER_NOT_ELIGIBLE,
    ERR_PLAN_NOT_APPROVED, ERR_STRATEGY_CAP_EXCEEDED, ERR_MANAGER_CAP_EXCEEDED,
    ERR_PACING_CAPACITY_EXCEEDED, ERR_SOD_VIOLATION, ERR_UNAUTHORIZED,
)
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, list_response
from services import domain
from util import dec
from validate import body, req_str, req_positive_num

bp = Blueprint("proposals", __name__)


def get_proposal_or_404(pid):
    p = STORE.proposals.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "proposal id does not exist")
    return p


@bp.route("/fof/vehicles/<vid>/proposals", methods=["POST"])
def create_proposal(vid):
    user_id, role = auth_context()
    require_role(role, ["Analyst"])
    vehicle = STORE.vehicles.get(vid)
    if vehicle is None:
        raise_err(ERR_NOT_FOUND, "vehicle id does not exist")
    data = body()
    program_id = req_str(data, "program_id")
    pacing_plan_id = req_str(data, "pacing_plan_id")
    proposed_amount = req_positive_num(data, "proposed_amount")
    program = STORE.programs.get(program_id)
    if program is None:
        raise_err(ERR_REF_NOT_FOUND, "program_id does not exist")
    if STORE.pacing_plans.get(pacing_plan_id) is None:
        raise_err(ERR_REF_NOT_FOUND, "pacing_plan_id does not exist")
    p = new_entity(STORE.proposals, {
        "vehicle_id": vid,
        "program_id": program_id,
        "pacing_plan_id": pacing_plan_id,
        "proposed_amount": proposed_amount,
        "recommended_by_analyst_id": user_id,
        "concentration_strategy_pct": None,
        "concentration_manager_pct": None,
        "status": "DRAFT",
    })
    return ok(public(p), status=201)


@bp.route("/fof/vehicles/<vid>/proposals", methods=["GET"])
def list_vehicle_proposals(vid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if STORE.vehicles.get(vid) is None:
        raise_err(ERR_NOT_FOUND, "vehicle id does not exist")
    rows = [p for p in STORE.proposals.values() if p["vehicle_id"] == vid]
    return list_response(rows, filters={"status": request.args.get("status")})


@bp.route("/fof/proposals/<pid>", methods=["GET"])
def get_proposal(pid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return ok(public(get_proposal_or_404(pid)))


@bp.route("/fof/proposals/<pid>/recommend", methods=["POST"])
def recommend_proposal(pid):
    user_id, role = auth_context()
    require_role(role, ["Analyst"])
    p = get_proposal_or_404(pid)
    prog = STORE.programs.get(p["program_id"])
    vehicle = STORE.vehicles.get(p["vehicle_id"])
    manager = STORE.managers.get(vehicle["manager_id"]) if vehicle else None
    if p["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "proposal is not in DRAFT")
    if prog is None or prog["status"] != "OPEN" or prog["posture"] != "NORMAL":
        raise_err(ERR_POSTURE_GATED,
                  "program must be OPEN with posture NORMAL")
    if vehicle is None or vehicle["status"] != "APPROVED":
        raise_err(ERR_VEHICLE_NOT_APPROVED, "vehicle is not APPROVED")
    if manager is None or manager["status"] != "APPROVED":
        raise_err(ERR_MANAGER_NOT_ELIGIBLE, "manager is not APPROVED")
    plan = STORE.pacing_plans.get(p["pacing_plan_id"])
    if (plan is None or plan["program_id"] != p["program_id"]
            or plan["status"] != "APPROVED"):
        raise_err(ERR_PLAN_NOT_APPROVED,
                  "pacing plan is not APPROVED for this program")
    if user_id != p["recommended_by_analyst_id"]:
        raise_err(ERR_UNAUTHORIZED,
                  "only the drafting analyst may recommend this proposal")
    domain.concentration_check(prog, p, vehicle)
    p["status"] = "RECOMMENDED"
    touch(p)
    return ok(public(p))


@bp.route("/fof/proposals/<pid>/ic-approve", methods=["POST"])
def ic_approve_proposal(pid):
    user_id, role = auth_context()
    require_role(role, ["InvestmentCommittee"])
    p = get_proposal_or_404(pid)
    prog = STORE.programs.get(p["program_id"])
    vehicle = STORE.vehicles.get(p["vehicle_id"])
    if p["status"] != "RECOMMENDED":
        raise_err(ERR_INVALID_STATE, "proposal is not RECOMMENDED")
    if prog is None or prog["status"] != "OPEN" or prog["posture"] != "NORMAL":
        raise_err(ERR_POSTURE_GATED,
                  "program must be OPEN with posture NORMAL")
    # Priority 9 (business_safety): segregation of duties fires before the
    # priority-14/15/18 constraint checks. The approver's StaffUser email
    # must differ from the recommending analyst's.
    approver = STORE.staff_users.get(user_id)
    recommender = STORE.staff_users.get(p["recommended_by_analyst_id"])
    if (approver is not None and recommender is not None
            and approver["email"] == recommender["email"]):
        raise_err(ERR_SOD_VIOLATION,
                  "IC approver and recommending analyst are the same person")
    if dec(p["concentration_strategy_pct"]) > dec(prog["strategy_cap_pct"]):
        raise_err(ERR_STRATEGY_CAP_EXCEEDED,
                  "post-trade strategy concentration exceeds strategy_cap_pct")
    if dec(p["concentration_manager_pct"]) > dec(prog["manager_cap_pct"]):
        raise_err(ERR_MANAGER_CAP_EXCEEDED,
                  "post-trade manager concentration exceeds manager_cap_pct")
    # Pacing capacity: the target row for the vehicle's (vintage_year,
    # strategy) under the APPROVED plan, minus already IC_APPROVED proposal
    # amounts for that year and strategy. When the plan carries no target
    # row for this (year, strategy) pair, the plan does not gate the
    # proposal and the check is skipped.
    plan = STORE.pacing_plans.get(p["pacing_plan_id"])
    if plan is not None and vehicle is not None:
        rows = [row for row in plan["target_commit_by_year"]
                if row["vintage_year"] == vehicle["vintage_year"]
                and row["strategy"] == vehicle["strategy"]]
        if rows:
            target = sum((dec(row["amount"]) for row in rows), dec(0))
            used = dec(0)
            for other in STORE.proposals.values():
                if (other["pacing_plan_id"] == plan["id"]
                        and other["status"] == "IC_APPROVED"
                        and other["id"] != p["id"]):
                    ov = STORE.vehicles.get(other["vehicle_id"])
                    if (ov is not None
                            and ov["vintage_year"] == vehicle["vintage_year"]
                            and ov["strategy"] == vehicle["strategy"]):
                        used += dec(other["proposed_amount"])
            if dec(p["proposed_amount"]) > target - used:
                raise_err(ERR_PACING_CAPACITY_EXCEEDED,
                          "proposed_amount exceeds remaining pacing capacity")
    p["status"] = "IC_APPROVED"
    touch(p)
    new_entity(STORE.commitments, {
        "program_id": p["program_id"],
        "vehicle_id": p["vehicle_id"],
        "proposal_id": p["id"],
        "sized_amount": p["proposed_amount"],
        "unfunded_amount": p["proposed_amount"],
        "status": "PENDING_DOCS",
        "executed_at": None,
    })
    return ok(public(p))


@bp.route("/fof/proposals/<pid>/ic-reject", methods=["POST"])
def ic_reject_proposal(pid):
    _, role = auth_context()
    require_role(role, ["InvestmentCommittee"])
    p = get_proposal_or_404(pid)
    if p["status"] != "RECOMMENDED":
        raise_err(ERR_INVALID_STATE, "proposal is not RECOMMENDED")
    p["status"] = "IC_REJECTED"
    touch(p)
    return ok(public(p))


@bp.route("/fof/proposals/<pid>/withdraw", methods=["POST"])
def withdraw_proposal(pid):
    user_id, role = auth_context()
    require_role(role, ["Analyst"])
    p = get_proposal_or_404(pid)
    if p["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "proposal is not in DRAFT")
    if user_id != p["recommended_by_analyst_id"]:
        raise_err(ERR_UNAUTHORIZED,
                  "only the drafting analyst may withdraw this proposal")
    p["status"] = "WITHDRAWN"
    touch(p)
    return ok(public(p))


@bp.route("/fof/proposals/<pid>/commitments", methods=["GET"])
def list_proposal_commitments(pid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_proposal_or_404(pid)
    rows = [c for c in STORE.commitments.values() if c["proposal_id"] == pid]
    return list_response(rows)
