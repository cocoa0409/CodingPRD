"""Test-driving endpoints: logical clock control and the daily sweep.

Sweep pinned order (PRD 3.9): (1) interest — DAILY_ACCRUAL per debit account,
MONTHLY_POST on month roll (its cash debit feeds step 3); (2) PDT flag
evaluation; (3) call evaluation on the official basis — cure satisfied OPEN
calls (MARKET_RECOVERY), expire OPEN calls at/past due_at (DISPUTED calls do
not expire), then issue at most one new call per account by severity.
"""
from flask import Blueprint

from authz import MARKET_OPS, require_roles
from calc import open_calls, recompute_account
from cascades import (
    accrue_interest_for_account,
    cure_open_calls,
    evaluate_pdt,
    issue_call,
    pending_call_for_account,
    posture_recheck,
)
from db import store
from errors import clock_regression
from response import success
from store_ops import json_body, req_clock_instant, touch
from timeutil import fmt_dt

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    data = json_body()
    to = req_clock_instant(data, "to_iso8601")
    require_roles([MARKET_OPS])
    # Priority 9: the logical clock never regresses; equal is allowed.
    if to < store.clock:
        raise clock_regression()
    store.clock = to
    return success({"current_utc": fmt_dt(store.clock)})


@bp.route("/_sweeps/daily", methods=["POST"])
def daily_sweep():
    require_roles([MARKET_OPS])
    today = store.clock.date()
    calls_issued = 0
    calls_cured = 0
    calls_expired = 0
    accruals_created = 0
    posts_created = 0
    pdt_set = 0
    pdt_cleared = 0

    accounts = sorted(
        (a for a in store.accounts.values() if a["account_status"] != "CLOSED"),
        key=lambda a: a["_seq"])

    # Step 1: interest (accruals, then month-roll posts; posts recompute cash).
    for account in accounts:
        accruals, posts = accrue_interest_for_account(account, today)
        accruals_created += accruals
        posts_created += posts

    # Step 2: pattern-day-trader evaluation over the trailing-5-date window.
    for account in accounts:
        result = evaluate_pdt(account)
        if result == "set":
            pdt_set += 1
        elif result == "cleared":
            pdt_cleared += 1

    # Step 3: call evaluation per account on the official basis, in the listed
    # order: issue new calls, cure satisfied OPEN calls (MARKET_RECOVERY),
    # expire OPEN calls at/past due_at (DISPUTED calls never expire).
    # Recomputing the derived fields is itself a mutation of the account
    # (PRD 2.7), so every evaluated account's version advances.
    for account in accounts:
        recompute_account(account)
        touch(account)
        pending = pending_call_for_account(account)
        if pending is not None:
            issue_call(account, pending[0], pending[1])
            calls_issued += 1
        calls_cured += cure_open_calls(account, "MARKET_RECOVERY")
        for call in open_calls(account["id"]):
            if store.clock >= call["due_at"]:
                call["call_status"] = "EXPIRED"
                touch(call)
                calls_expired += 1
        posture_recheck(account)

    return success({
        "calls_issued": calls_issued,
        "calls_cured": calls_cured,
        "calls_expired": calls_expired,
        "interest_accruals_created": accruals_created,
        "interest_posts_created": posts_created,
        "pdt_flags_set": pdt_set,
        "pdt_flags_cleared": pdt_cleared,
    })
