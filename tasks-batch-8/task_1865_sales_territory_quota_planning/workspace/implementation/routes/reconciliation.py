"""ReconciliationRun endpoints."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import get_user_context, require_role
from response import success_object, success_list
from util import (get_body, reject_unknown_fields, require_fields, req_int,
                  find_or_404, paginate, stamp_new, touch)
from services import calc

bp = Blueprint("reconciliation", __name__)

ADMIN = ("SalesOpsAdmin",)
ALL = ("SalesOpsAdmin", "SalesOpsAnalyst", "RevOpsManager", "SalesRep")


@bp.route("/sales-planning/reconciliation-runs", methods=["POST"])
def create_run():
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    body = get_body()
    reject_unknown_fields(body, {"plan_year_id"})
    require_fields(body, ["plan_year_id"])
    plan = find_or_404(store.plan_years, body["plan_year_id"], "plan year")

    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if plan["status"] not in ("SUBMISSIONS_CLOSED", "RECONCILED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Reconciliation compute requires plan status SUBMISSIONS_CLOSED or RECONCILED",
                       409)

    results = calc.compute_reconciliation_results(plan)
    run = stamp_new({
        "plan_year_id": plan["id"],
        "policy_used": plan["reconciliation_policy"],
        "results": results,
        "status": "COMPUTED",
    })
    store.reconciliation_runs[run["id"]] = run
    return success_object(calc.ser_reconciliation_run(run), status=201)


@bp.route("/sales-planning/reconciliation-runs", methods=["GET"])
def list_runs():
    ctx = get_user_context()
    require_role(ctx, ALL)
    items = list(store.reconciliation_runs.values())
    if (v := request.args.get("plan_year_id")) is not None:
        items = [r for r in items if r["plan_year_id"] == v]
    if (v := request.args.get("status")) is not None:
        items = [r for r in items if r["status"] == v]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page, limit, offset, total = paginate(items, request.args)
    return success_list([calc.ser_reconciliation_run(r) for r in page], limit, offset, total)


@bp.route("/sales-planning/reconciliation-runs/<rid>", methods=["GET"])
def get_run(rid):
    ctx = get_user_context()
    require_role(ctx, ALL)
    r = find_or_404(store.reconciliation_runs, rid, "reconciliation run")
    return success_object(calc.ser_reconciliation_run(r))


@bp.route("/sales-planning/reconciliation-runs/<rid>/apply", methods=["POST"])
def apply_run(rid):
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    run = find_or_404(store.reconciliation_runs, rid, "reconciliation run")
    body = get_body()
    reject_unknown_fields(body, {"expected_plan_year_version"})
    plan = find_or_404(store.plan_years, run["plan_year_id"], "plan year")

    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if plan["status"] not in ("SUBMISSIONS_CLOSED", "RECONCILED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Reconciliation apply requires plan status SUBMISSIONS_CLOSED or RECONCILED",
                       409)

    # OCC
    if "expected_plan_year_version" not in body or body["expected_plan_year_version"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "expected_plan_year_version is required", 400)
    expected = req_int(body, "expected_plan_year_version")
    if expected != plan["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_plan_year_version does not match the plan's current version", 412)

    if run["status"] != "COMPUTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot apply run in status {run['status']}", 409)

    # Write finals
    run["status"] = "APPLIED"
    touch(run)
    affected = []
    for row in run["results"]:
        t = store.territories.get(row["territory_id"])
        if t is None:
            continue
        if t["final_quota_cents"] != row["final_cents"]:
            t["final_quota_cents"] = row["final_cents"]
            touch(t)
        affected.append(t["id"])

    # First apply: SUBMISSIONS_CLOSED -> RECONCILED; superseding apply stays RECONCILED.
    # The status flip must precede the cascade so final-share/pct recompute sees the
    # reconciled denominator basis.
    if plan["status"] == "SUBMISSIONS_CLOSED":
        plan["status"] = "RECONCILED"

    # Cascade hop 2/3: final shares + ramp + attainment pct for ACTIVE assignments
    for tid in affected:
        t = store.territories.get(tid)
        if t is not None:
            calc._recompute_assignment_shares_for_territory(t)

    touch(plan)
    return success_object(calc.ser_reconciliation_run(run))


@bp.route("/sales-planning/reconciliation-runs/<rid>/discard", methods=["POST"])
def discard_run(rid):
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    run = find_or_404(store.reconciliation_runs, rid, "reconciliation run")
    plan = find_or_404(store.plan_years, run["plan_year_id"], "plan year")
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if plan["status"] not in ("SUBMISSIONS_CLOSED", "RECONCILED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Reconciliation discard requires plan status SUBMISSIONS_CLOSED or RECONCILED",
                       409)
    if run["status"] != "COMPUTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot discard run in status {run['status']}", 409)
    run["status"] = "DISCARDED"
    touch(run)
    return success_object(calc.ser_reconciliation_run(run))
