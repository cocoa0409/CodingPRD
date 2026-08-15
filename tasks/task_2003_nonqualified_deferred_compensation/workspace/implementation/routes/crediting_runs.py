"""Crediting run endpoints."""
from flask import Blueprint, request

import db
from errors import (
    ERR_PLAN_NOT_ACTIVE,
    ERR_STALE_VERSION,
    ERR_CREDITING_PERIOD_OVERLAP,
    ERR_INDEX_RATE_MISSING,
    ERR_CREDITING_RUN_STATE_INVALID,
    ERR_CREDITING_RUN_NOT_LATEST,
    raise_err,
)
from middleware import user_context, require_role
from response import ok_object
from routes.plans import _list_response
from services.core import (
    body,
    req_date,
    req_int,
    get_or_404,
    stamp_new,
    touch,
    recompute_account_balances,
    recompute_trusts_for_plan,
)
from util import CLOCK, fmt_date, parse_date, round_half_up_div

bp = Blueprint("crediting_runs", __name__)


def run_view(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "plan_id": r["plan_id"],
        "period_start": r["period_start"],
        "period_end": r["period_end"],
        "index_rates": r["index_rates"],
        "status": r["status"],
        "days_in_period": r["days_in_period"],
        "total_gain_cents": r["total_gain_cents"],
    }


def _validate_index_rates(raw):
    from errors import ERR_INVALID_REQUEST

    if raw is None:
        return None
    if not isinstance(raw, list):
        raise_err(ERR_INVALID_REQUEST, "index_rates must be an array")
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise_err(ERR_INVALID_REQUEST, "index_rates entries must be objects")
        fid = item.get("fund_id")
        rate = item.get("annual_rate_bp")
        if not isinstance(fid, str) or not fid:
            raise_err(ERR_INVALID_REQUEST, "index_rates entries require fund_id")
        if isinstance(rate, bool) or not isinstance(rate, int):
            raise_err(ERR_INVALID_REQUEST, "index_rates entries require integer annual_rate_bp")
        if rate < -10000 or rate > 10000:
            raise_err(ERR_INVALID_REQUEST, "annual_rate_bp out of range")
        out.append({"fund_id": fid, "annual_rate_bp": rate})
    return out


@bp.post("/api/crediting-runs")
def create_run():
    data = body()
    from errors import ERR_INVALID_REQUEST, ERR_INVALID_DATE_RANGE

    plan_id = data.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise_err(ERR_INVALID_REQUEST, "plan_id is required and must be a string")
    p_start = req_date(data, "period_start")
    p_end = req_date(data, "period_end")
    if p_start >= p_end:
        raise_err(ERR_INVALID_DATE_RANGE, "period_start must be before period_end")
    index_rates = _validate_index_rates(data.get("index_rates"))
    expected = req_int(data, "expected_plan_version")

    user_id, role = user_context()
    require_role(role, {"BenefitsAdministrator"})
    plan = get_or_404(db.plans, plan_id, "Plan")
    if expected != plan["version"]:
        raise_err(ERR_STALE_VERSION, "expected_plan_version does not match current Plan.version")
    if plan["status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to post a crediting run")

    # Half-open overlap against existing POSTED runs of the plan
    for r in db.crediting_runs.values():
        if r["plan_id"] != plan_id or r["status"] != "POSTED":
            continue
        o_start = parse_date(r["period_start"])
        o_end = parse_date(r["period_end"])
        if p_start < o_end and p_end > o_start:
            raise_err(ERR_CREDITING_PERIOD_OVERLAP, "Crediting period overlaps an existing POSTED run")

    # Every ACTIVE INDEX_LINKED fund of the plan must appear in index_rates
    rates_by_fund = {ir["fund_id"]: ir["annual_rate_bp"] for ir in (index_rates or [])}
    index_funds = [
        f for f in db.notional_funds.values() if f["plan_id"] == plan_id and f["crediting_mode"] == "INDEX_LINKED"
    ]
    for f in index_funds:
        if f["id"] not in rates_by_fund:
            raise_err(ERR_INDEX_RATE_MISSING, f"index_rates missing entry for INDEX_LINKED fund {f['id']}")

    days = (p_end - p_start).days

    run = stamp_new(
        {
            "plan_id": plan_id,
            "period_start": fmt_date(p_start),
            "period_end": fmt_date(p_end),
            "index_rates": index_rates or [],
            "status": "POSTED",
            "days_in_period": days,
            "total_gain_cents": 0,
        }
    )
    db.crediting_runs[run["id"]] = run

    # Post per-(account, fund) CREDITING_GAIN entries, round per entry then sum
    accounts = [
        a
        for a in db.accounts.values()
        if a["plan_id"] == plan_id and a["status"] in ("ACTIVE", "FLAGGED_FOR_INCLUSION")
    ]
    accounts.sort(key=lambda a: a["created_at"])
    total_gain = 0
    funds_by_id = {f["id"]: f for f in db.notional_funds.values() if f["plan_id"] == plan_id}
    touched_accounts = set()
    for account in accounts:
        # fund-specific settled balances as of run creation
        per_fund = {}
        for e in db.ledger_entries.values():
            if e["account_id"] != account["id"] or e["entry_status"] != "POSTED":
                continue
            fid = e.get("fund_id")
            if fid is None:
                continue
            per_fund[fid] = per_fund.get(fid, 0) + e["amount_cents"]
        for fid in sorted(per_fund.keys()):
            bal = per_fund[fid]
            if bal <= 0:
                continue
            fund = funds_by_id.get(fid)
            if fund is None:
                continue
            if fund["crediting_mode"] == "FIXED_RATE":
                rate = fund["annual_rate_bp"]
            else:
                rate = rates_by_fund[fid]  # existence guaranteed above
            gain = round_half_up_div(bal * rate * days, 10000 * 365)
            ts = CLOCK.stamp()
            entry = {
                "id": db.new_id(),
                "created_at": ts,
                "account_id": account["id"],
                "entry_type": "CREDITING_GAIN",
                "amount_cents": gain,
                "fund_id": fid,
                "crediting_run_id": run["id"],
                "election_id": None,
                "distribution_request_id": None,
                "entry_status": "POSTED",
                "entry_date": fmt_date(CLOCK.date()),
            }
            db.ledger_entries[entry["id"]] = entry
            total_gain += gain
            touched_accounts.add(account["id"])
    run["total_gain_cents"] = total_gain
    for aid in touched_accounts:
        recompute_account_balances(db.accounts[aid])
    recompute_trusts_for_plan(plan_id)
    touch(plan)
    return ok_object(run_view(run), 201)


@bp.get("/api/crediting-runs")
def list_runs():
    user_context()
    items = list(db.crediting_runs.values())
    plan_id = request.args.get("plan_id")
    if plan_id is not None:
        items = [r for r in items if r["plan_id"] == plan_id]
    return _list_response([run_view(r) for r in items], request.args)


@bp.get("/api/crediting-runs/<runId>")
def get_run(runId):
    user_context()
    r = get_or_404(db.crediting_runs, runId, "CreditingRun")
    return ok_object(run_view(r))


@bp.post("/api/crediting-runs/<runId>/reverse")
def reverse_run(runId):
    body()
    user_id, role = user_context()
    require_role(role, {"BenefitsAdministrator"})
    run = get_or_404(db.crediting_runs, runId, "CreditingRun")
    if run["status"] != "POSTED":
        raise_err(ERR_CREDITING_RUN_STATE_INVALID, "Reverse requires status POSTED")

    # Latest POSTED run for the plan: max period_end, tie-break later created_at
    posted = [r for r in db.crediting_runs.values() if r["plan_id"] == run["plan_id"] and r["status"] == "POSTED"]
    latest = max(posted, key=lambda r: (r["period_end"], r["created_at"]))
    if latest["id"] != run["id"]:
        raise_err(ERR_CREDITING_RUN_NOT_LATEST, "Only the latest POSTED run of the plan may be reversed")

    gains = [e for e in db.ledger_entries.values() if e["crediting_run_id"] == run["id"] and e["entry_type"] == "CREDITING_GAIN"]
    gains.sort(key=lambda e: e["created_at"])
    touched = set()
    for gain in gains:
        ts = CLOCK.stamp()
        rev = {
            "id": db.new_id(),
            "created_at": ts,
            "account_id": gain["account_id"],
            "entry_type": "CREDITING_REVERSAL",
            "amount_cents": -gain["amount_cents"],
            "fund_id": gain["fund_id"],
            "crediting_run_id": run["id"],
            "election_id": None,
            "distribution_request_id": None,
            "entry_status": "POSTED",
            "entry_date": fmt_date(CLOCK.date()),
        }
        db.ledger_entries[rev["id"]] = rev
        touched.add(gain["account_id"])
    run["status"] = "REVERSED"
    touch(run)
    for aid in touched:
        recompute_account_balances(db.accounts[aid])
    recompute_trusts_for_plan(run["plan_id"])
    return ok_object(run_view(run))
