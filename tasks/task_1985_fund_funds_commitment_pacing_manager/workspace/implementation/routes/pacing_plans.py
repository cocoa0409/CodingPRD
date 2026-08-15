"""PacingPlan endpoints: create, approve (pacing targets), supersede (OCC)."""

from flask import Blueprint, request

from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_REF_NOT_FOUND, ERR_INVALID_STATE,
    ERR_POSTURE_GATED, ERR_MIX_SUM_INVALID, ERR_ACTIVE_PLAN_EXISTS,
    ERR_PLAN_NOT_DRAFT, ERR_STALE_VERSION, ERR_INVALID_REQUEST,
)
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, list_response
from services import domain
from util import dec, is_num
from validate import body, req_str, req_int

bp = Blueprint("pacing_plans", __name__)


def get_program_or_404(pid):
    prog = STORE.programs.get(pid)
    if prog is None:
        raise_err(ERR_NOT_FOUND, "program id does not exist")
    return prog


def get_plan_or_404(pid, plan_id):
    plan = STORE.pacing_plans.get(plan_id)
    if plan is None or plan["program_id"] != pid:
        raise_err(ERR_NOT_FOUND, "pacing plan id does not exist")
    return plan


def _validate_mix(mix):
    """Shape-check target_strategy_mix (weight sum / strategy validity are
    enforced at approve time; creation validates structure only)."""
    if not isinstance(mix, list):
        raise_err(ERR_INVALID_REQUEST, "target_strategy_mix must be a list")
    for entry in mix:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST,
                      "target_strategy_mix entries must be objects")
        if "strategy" not in entry or "weight" not in entry:
            raise_err(ERR_INVALID_REQUEST,
                      "each mix entry needs strategy and weight")
        if not isinstance(entry["strategy"], str):
            raise_err(ERR_INVALID_REQUEST, "mix strategy must be a string")
        if not is_num(entry["weight"]):
            raise_err(ERR_INVALID_REQUEST, "mix weight must be a number")


@bp.route("/fof/programs/<pid>/pacing-plans", methods=["POST"])
def create_plan(pid):
    _, role = auth_context()
    require_role(role, ["Analyst"])
    prog = get_program_or_404(pid)
    data = body()
    plan_label = req_str(data, "plan_label")
    horizon_years = req_int(data, "horizon_years")
    if horizon_years < 1:
        raise_err(ERR_INVALID_REQUEST, "horizon_years must be >= 1")
    start_vintage_year = req_int(data, "start_vintage_year")
    if start_vintage_year < 2000:
        raise_err(ERR_INVALID_REQUEST, "start_vintage_year must be >= 2000")
    mix = data.get("target_strategy_mix")
    _validate_mix(mix)
    for p in STORE.pacing_plans.values():
        if p["program_id"] == pid and p["plan_label"] == plan_label:
            raise_err(ERR_INVALID_REQUEST,
                      "plan_label must be unique within the program")
    plan = new_entity(STORE.pacing_plans, {
        "program_id": prog["id"],
        "plan_label": plan_label,
        "horizon_years": horizon_years,
        "start_vintage_year": start_vintage_year,
        "target_strategy_mix": [
            {"strategy": e["strategy"], "weight": e["weight"]} for e in mix],
        "status": "DRAFT",
        "target_commit_by_year": [],
        "projected_total_commit": 0,
    })
    return ok(public(plan), status=201)


@bp.route("/fof/programs/<pid>/pacing-plans", methods=["GET"])
def list_plans(pid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_program_or_404(pid)
    rows = [p for p in STORE.pacing_plans.values() if p["program_id"] == pid]
    return list_response(rows, filters={"status": request.args.get("status")})


@bp.route("/fof/programs/<pid>/pacing-plans/<plan_id>", methods=["GET"])
def get_plan(pid, plan_id):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_program_or_404(pid)
    return ok(public(get_plan_or_404(pid, plan_id)))


def _check_mix_business(mix):
    """Approve-time mix checks: at most 4 entries, weights sum exactly to
    1.0, every strategy declared."""
    if len(mix) > 4:
        raise_err(ERR_MIX_SUM_INVALID,
                  "target_strategy_mix may hold at most 4 entries")
    total = sum((dec(e["weight"]) for e in mix), dec(0))
    if total != dec(1):
        raise_err(ERR_MIX_SUM_INVALID,
                  "target_strategy_mix weights must sum to exactly 1.0")
    for e in mix:
        if e["strategy"] not in domain.STRATEGIES:
            raise_err(ERR_MIX_SUM_INVALID,
                      "mix strategy %s is not a declared strategy"
                      % e["strategy"])


@bp.route("/fof/programs/<pid>/pacing-plans/<plan_id>/approve", methods=["POST"])
def approve_plan(pid, plan_id):
    _, role = auth_context()
    require_role(role, ["CIO"])
    prog = get_program_or_404(pid)
    plan = get_plan_or_404(pid, plan_id)
    if plan["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "pacing plan is not in DRAFT")
    if prog["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "program is not OPEN")
    if prog["posture"] == "FROZEN":
        raise_err(ERR_POSTURE_GATED, "program posture is FROZEN")
    _check_mix_business(plan["target_strategy_mix"])
    for p in STORE.pacing_plans.values():
        if (p["program_id"] == pid and p["id"] != plan_id
                and p["status"] == "APPROVED"):
            raise_err(ERR_ACTIVE_PLAN_EXISTS,
                      "another pacing plan is already APPROVED")
    plan["status"] = "APPROVED"
    domain.run_pacing_targets(prog, plan)
    touch(plan)
    return ok(public(plan))


@bp.route("/fof/programs/<pid>/pacing-plans/<plan_id>/supersede", methods=["POST"])
def supersede_plan(pid, plan_id):
    _, role = auth_context()
    require_role(role, ["CIO"])
    data = body()
    prog = get_program_or_404(pid)
    plan = get_plan_or_404(pid, plan_id)
    replacement_id = data.get("replacement_plan_id")
    if replacement_id is None:
        raise_err(ERR_INVALID_REQUEST, "replacement_plan_id is required")
    replacement = STORE.pacing_plans.get(replacement_id)
    if replacement is None:
        raise_err(ERR_REF_NOT_FOUND, "replacement_plan_id does not exist")
    expected = data.get("expected_program_version")
    if expected is None:
        raise_err(ERR_INVALID_REQUEST, "expected_program_version is required")
    if expected != prog["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_program_version does not match the current version")
    if plan["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "pacing plan is not APPROVED")
    if prog["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "program is not OPEN")
    if prog["posture"] == "FROZEN":
        raise_err(ERR_POSTURE_GATED, "program posture is FROZEN")
    if (replacement["program_id"] != pid or replacement["status"] != "DRAFT"):
        raise_err(ERR_PLAN_NOT_DRAFT,
                  "replacement plan must be DRAFT and belong to this program")
    _check_mix_business(replacement["target_strategy_mix"])
    # Atomic transition: old -> SUPERSEDED, replacement -> APPROVED with
    # targets, DRAFT proposals on the old plan -> WITHDRAWN, program bump.
    plan["status"] = "SUPERSEDED"
    touch(plan)
    replacement["status"] = "APPROVED"
    domain.run_pacing_targets(prog, replacement)
    touch(replacement)
    for p in STORE.proposals.values():
        if (p["pacing_plan_id"] == plan_id and p["program_id"] == pid
                and p["status"] == "DRAFT"):
            p["status"] = "WITHDRAWN"
            touch(p)
    touch(prog)
    return ok(public(replacement))


# ---------------------------------------------------------------------------
# Flat forms.
# ---------------------------------------------------------------------------

@bp.route("/fof/pacing-plans/<plan_id>", methods=["GET"])
def get_plan_flat(plan_id):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    plan = STORE.pacing_plans.get(plan_id)
    if plan is None:
        raise_err(ERR_NOT_FOUND, "pacing plan id does not exist")
    return ok(public(plan))


@bp.route("/fof/pacing-plans/<plan_id>/proposals", methods=["GET"])
def list_plan_proposals(plan_id):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    plan = STORE.pacing_plans.get(plan_id)
    if plan is None:
        raise_err(ERR_NOT_FOUND, "pacing plan id does not exist")
    rows = [p for p in STORE.proposals.values()
            if p["pacing_plan_id"] == plan_id]
    return list_response(rows,
                         filters={"status": request.args.get("status")})
