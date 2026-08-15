"""ValuationRun endpoints: create/compute/certify/void plus reverse-reachability
list endpoints for runs and ParticipantAccrual rows."""

from decimal import Decimal

from flask import Blueprint, request

from db import store
from middleware import require_roles
from response import success_object, success_list, parse_pagination, list_page
from errors import (
    invalid_state, plan_terminated, validation, not_found, stale_version, ApiError,
    ERR_PLAN_YEAR_MISMATCH, ERR_REFERENCE_NOT_LOCKED,
    ERR_SEGREGATION_OF_DUTIES, ERR_ACTUARY_NOT_ENROLLED,
)
from validate import body_of, req_int, req_str
from services.core import (
    base_record, touch, public, get_plan, get_run, get_batch, get_aset,
    get_asset_valuation, get_participant, get_demand, r2d, D,
    compute_run_accruals, run_accruals, posture_for_pct,
    demand_for_plan, recompute_demand, due_date_for, fmt_ts,
)

bp = Blueprint("runs", __name__)

READ_ROLES = ["PlanAdmin", "Actuary", "SeniorActuary", "Auditor"]
ACTUARY_ROLES = ["Actuary", "SeniorActuary"]


def _plan_active_gate(plan):
    if plan["status"] != "ACTIVE":
        raise plan_terminated()


# ---------------------------------------------------------------------------
# ValuationRun lifecycle
# ---------------------------------------------------------------------------

@bp.route("/v1/plans/<plan_id>/valuation-runs", methods=["POST"])
def create_valuation_run(plan_id):
    role, user_id = require_roles(ACTUARY_ROLES)
    plan = get_plan(plan_id)
    _plan_active_gate(plan)
    body = body_of(request)

    # body-referenced resources must exist (existence stage)
    census_batch_id = body.get("census_batch_id")
    assumption_set_id = body.get("assumption_set_id")
    asset_valuation_id = body.get("asset_valuation_id")
    if isinstance(census_batch_id, str):
        get_batch(census_batch_id)
    if isinstance(assumption_set_id, str):
        get_aset(assumption_set_id)
    if isinstance(asset_valuation_id, str):
        get_asset_valuation(asset_valuation_id)

    # priority 11: plan-year and same-plan referential alignment
    py = body.get("plan_year")
    if isinstance(py, int) and not isinstance(py, bool) and py != plan["plan_year"]:
        raise ApiError(ERR_PLAN_YEAR_MISMATCH, 422, "plan_year differs from the plan's plan_year")
    for ref, label in (
        (census_batch_id, "census_batch_id"),
        (assumption_set_id, "assumption_set_id"),
        (asset_valuation_id, "asset_valuation_id"),
    ):
        if isinstance(ref, str):
            ent = (
                store.census_batches.get(ref)
                or store.assumption_sets.get(ref)
                or store.asset_valuations.get(ref)
            )
            if ent is not None and (ent["plan_id"] != plan["id"] or ent["plan_year"] != plan["plan_year"]):
                raise ApiError(ERR_PLAN_YEAR_MISMATCH, 422, f"{label} does not belong to this plan and plan_year")

    # priority 22: body well-formedness
    plan_year = req_int(body, "plan_year")
    census_batch_id = req_str(body, "census_batch_id")
    assumption_set_id = req_str(body, "assumption_set_id")
    asset_valuation_id = req_str(body, "asset_valuation_id")

    rec = base_record()
    rec.update({
        "plan_id": plan["id"],
        "plan_year": plan_year,
        "census_batch_id": census_batch_id,
        "assumption_set_id": assumption_set_id,
        "asset_valuation_id": asset_valuation_id,
        "status": "INITIATED",
        "funding_target": None,
        "normal_cost": None,
        "aftap_pct": None,
        "created_by_actuary_id": user_id,
        "certified_by_actuary_id": None,
    })
    store.valuation_runs[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/v1/plans/<plan_id>/valuation-runs", methods=["GET"])
def list_valuation_runs(plan_id):
    require_roles(READ_ROLES)
    plan = get_plan(plan_id)
    limit, offset = parse_pagination(request.args)
    items = [r for r in store.valuation_runs.values() if r["plan_id"] == plan["id"]]
    page, total = list_page(items, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/v1/valuation-runs/<run_id>", methods=["GET"])
def fetch_valuation_run(run_id):
    require_roles(READ_ROLES)
    run = get_run(run_id)
    return success_object(public(run))


@bp.route("/v1/valuation-runs/<run_id>/compute", methods=["POST"])
def compute_valuation_run(run_id):
    require_roles(ACTUARY_ROLES)
    run = get_run(run_id)
    if run["status"] != "INITIATED":
        raise invalid_state("ValuationRun is not INITIATED")
    plan = store.plans.get(run["plan_id"])
    if plan is not None and plan["status"] != "ACTIVE":
        raise plan_terminated()
    # priority 13: referenced census LOCKED, assumptions LOCKED, asset valuation same-plan
    batch = store.census_batches.get(run["census_batch_id"])
    aset = store.assumption_sets.get(run["assumption_set_id"])
    ava = store.asset_valuations.get(run["asset_valuation_id"])
    if batch is None or batch["status"] != "LOCKED":
        raise ApiError(ERR_REFERENCE_NOT_LOCKED, 422, "Referenced census batch is not LOCKED")
    if aset is None or aset["status"] != "LOCKED":
        raise ApiError(ERR_REFERENCE_NOT_LOCKED, 422, "Referenced assumption set is not LOCKED")
    if ava is None or ava["plan_id"] != run["plan_id"]:
        raise ApiError(ERR_REFERENCE_NOT_LOCKED, 422, "Referenced asset valuation does not belong to this plan")

    compute_run_accruals(run)
    run["status"] = "COMPUTED"
    touch(run)
    return success_object(public(run))


@bp.route("/v1/valuation-runs/<run_id>/certify", methods=["POST"])
def certify_valuation_run(run_id):
    role, user_id = require_roles(["SeniorActuary"])
    run = get_run(run_id)
    # priority 4: from-state
    if run["status"] != "COMPUTED":
        raise invalid_state("ValuationRun is not COMPUTED")
    plan = store.plans.get(run["plan_id"])
    if plan is None:
        raise not_found("Plan not found")
    # priority 5: plan-active gate
    if plan["status"] != "ACTIVE":
        raise plan_terminated()
    body = body_of(request)
    # OCC: expected_plan_version == Plan.version
    epv = body.get("expected_plan_version")
    if epv is not None:
        if isinstance(epv, bool) or not isinstance(epv, int):
            raise validation("expected_plan_version must be an integer")
        if epv != plan["version"]:
            raise stale_version()
    # priority 6: segregation of duties
    if user_id == run["created_by_actuary_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 422, "Certifier must differ from the run's creator")
    # priority 7: enrollment
    act = store.actuaries.get(user_id)
    if act is None or act.get("enrollment_status") != "ENROLLED":
        raise ApiError(ERR_ACTUARY_NOT_ENROLLED, 422, "Acting actuary is not ENROLLED")
    # missing expected_plan_version surfaces as body validation (lowest priority)
    if epv is None:
        raise validation("Missing required field: expected_plan_version")

    # --- certification ---
    ava = store.asset_valuations.get(run["asset_valuation_id"])
    ledger = store.credit_balance_ledgers.get(plan["id"])
    smoothed = r2d(ava["smoothed_value"]) if ava else Decimal("0.00")
    carry = r2d(ledger["carryover_balance"]) if ledger else Decimal("0.00")
    pre = r2d(ledger["prefunding_balance"]) if ledger else Decimal("0.00")
    funding_target = r2d(run["funding_target"] or 0)
    if funding_target > 0:
        aftap = r2d(Decimal(100) * (smoothed - (carry + pre)) / funding_target)
    else:
        aftap = Decimal("0.00")

    run["aftap_pct"] = float(aftap)
    run["certified_by_actuary_id"] = user_id
    run["status"] = "CERTIFIED"
    touch(run)

    # cascade hop 1: plan version + certified AFTAP + posture
    plan["certified_aftap_pct"] = float(aftap)
    posture = posture_for_pct(aftap)
    plan["current_posture"] = posture
    touch(plan)

    # previously CERTIFIED runs of the same plan -> SUPERSEDED
    for other in store.valuation_runs.values():
        if other["id"] != run["id"] and other["plan_id"] == plan["id"] and other["status"] == "CERTIFIED":
            other["status"] = "SUPERSEDED"
            touch(other)

    # cascade hop 2: freeze/unfreeze this run's accrual rows
    frozen_flag = posture == "ACCRUAL_FROZEN"
    for row in run_accruals(run["id"]):
        if row["frozen"] != frozen_flag:
            row["frozen"] = frozen_flag
            touch(row)

    # cascade hop 3+4: contribution demand create/recompute + auto-transition
    demand = demand_for_plan(plan["id"])
    if demand is None:
        demand = base_record()
        demand.update({
            "plan_id": plan["id"],
            "plan_year": run["plan_year"],
            "valuation_run_id": run["id"],
            "status": "OPEN",
            "excise_accrued": 0.0,
            "due_date": fmt_ts(due_date_for(plan["plan_year"])),
        })
        store.contribution_demands[demand["id"]] = demand
    else:
        demand["valuation_run_id"] = run["id"]
    recompute_demand(demand)
    touch(demand)

    # cascade: every DRAFT or AMENDED PBGC filing of the plan -> VOID
    for f in store.pbgc_filings.values():
        if f["plan_id"] == plan["id"] and f["status"] in ("DRAFT", "AMENDED"):
            f["status"] = "VOID"
            touch(f)

    return success_object(public(run))


@bp.route("/v1/valuation-runs/<run_id>/void", methods=["POST"])
def void_valuation_run(run_id):
    require_roles(ACTUARY_ROLES)
    run = get_run(run_id)
    if run["status"] not in ("INITIATED", "COMPUTED"):
        raise invalid_state("ValuationRun cannot be voided from its current status")
    plan = store.plans.get(run["plan_id"])
    if plan is not None and plan["status"] != "ACTIVE":
        raise plan_terminated()
    # accrual rows are retained for audit; excluded from aggregations (which
    # only ever run at compute time on INITIATED runs)
    run["status"] = "VOID"
    touch(run)
    return success_object(public(run))


# ---------------------------------------------------------------------------
# Reverse-reachability list endpoints
# ---------------------------------------------------------------------------

@bp.route("/v1/census-batches/<batch_id>/valuation-runs", methods=["GET"])
def list_runs_by_census(batch_id):
    require_roles(READ_ROLES)
    batch = get_batch(batch_id)
    limit, offset = parse_pagination(request.args)
    items = [r for r in store.valuation_runs.values() if r["census_batch_id"] == batch["id"]]
    page, total = list_page(items, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/v1/assumption-sets/<set_id>/valuation-runs", methods=["GET"])
def list_runs_by_assumption_set(set_id):
    require_roles(READ_ROLES)
    aset = get_aset(set_id)
    limit, offset = parse_pagination(request.args)
    items = [r for r in store.valuation_runs.values() if r["assumption_set_id"] == aset["id"]]
    page, total = list_page(items, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/v1/asset-valuations/<valuation_id>/valuation-runs", methods=["GET"])
def list_runs_by_asset_valuation(valuation_id):
    require_roles(READ_ROLES)
    ava = get_asset_valuation(valuation_id)
    limit, offset = parse_pagination(request.args)
    items = [r for r in store.valuation_runs.values() if r["asset_valuation_id"] == ava["id"]]
    page, total = list_page(items, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/v1/valuation-runs/<run_id>/accruals", methods=["GET"])
def list_run_accruals(run_id):
    require_roles(READ_ROLES)
    run = get_run(run_id)
    limit, offset = parse_pagination(request.args)
    page, total = list_page(run_accruals(run["id"]), limit, offset)
    return success_list([public(a) for a in page], limit, offset, total)


@bp.route("/v1/participants/<participant_id>/accruals", methods=["GET"])
def list_participant_accruals(participant_id):
    require_roles(READ_ROLES)
    participant = get_participant(participant_id)
    limit, offset = parse_pagination(request.args)
    items = [a for a in store.participant_accruals.values() if a["participant_id"] == participant["id"]]
    page, total = list_page(items, limit, offset)
    return success_list([public(a) for a in page], limit, offset, total)
