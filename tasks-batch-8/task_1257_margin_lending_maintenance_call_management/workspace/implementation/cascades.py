"""Cascade engine: account recompute, call issuance/cure/expiry, posture
reconciliation, interest accrual/posting, PDT evaluation, liquidation fills.

Touch policy (PRD 2.7/2.8/2.11):
- one client write = one account version increment, covering the write itself
  plus the derived-field recompute it triggers;
- automatic posture transitions (ACTIVE<->RESTRICTED) are separate account
  mutations and bump the version again when they actually flip;
- sweep step 3 recomputes every live account's official fields, which counts
  as a mutation (version bump) even when nothing else changed;
- every MarginCall state transition stamps the call (version bump) and is
  followed by the account posture recheck.
"""
from datetime import timedelta

from calc import (
    CALL_DEADLINE_HOURS,
    NON_TERMINAL_CALL_STATES,
    NON_TERMINAL_ORDER_STATES,
    PDT_MIN_DAY_TRADES,
    PDT_RATIO_NUM,
    binding_official_excess,
    call_cure_satisfied,
    calls_of_account,
    daily_accrual_amount,
    non_terminal_calls,
    open_calls,
    pending_call_for_account,
    positions_of_account,
    recompute_account,
    select_rate_tier,
)
from db import store
from store_ops import new_id, stamp_ledger, stamp_new, touch
from timeutil import days_in_month, month_of


# ---------------------------------------------------------------------------
# Account posture
# ---------------------------------------------------------------------------
def posture_recheck(account):
    """PRD 2.11: flip RESTRICTED -> ACTIVE when the last non-terminal call
    resolves; ACTIVE -> RESTRICTED the moment a call stands OPEN."""
    if account["account_status"] == "CLOSED":
        return False
    live = non_terminal_calls(account["id"])
    if account["account_status"] == "RESTRICTED" and not live:
        account["account_status"] = "ACTIVE"
        touch(account)
        return True
    if account["account_status"] == "ACTIVE" and any(
            c["call_status"] == "OPEN" for c in live):
        account["account_status"] = "RESTRICTED"
        touch(account)
        return True
    return False


# ---------------------------------------------------------------------------
# MarginCall lifecycle
# ---------------------------------------------------------------------------
def issue_call(account, call_type, amount):
    call = {
        "id": new_id(),
        "account_id": account["id"],
        "call_type": call_type,
        "call_status": "OPEN",
        "call_amount_cents": amount,
        "issued_at": store.clock,
        "due_at": store.clock + timedelta(hours=CALL_DEADLINE_HOURS[call_type]),
        "resolved_at": None,
        "cure_method": None,
    }
    stamp_new(call)
    store.calls[call["id"]] = call
    # Issuance flips ACTIVE -> RESTRICTED (PRD 2.11).
    posture_recheck(account)
    return call


def resolve_call(call, status, cure_method):
    call["call_status"] = status
    call["cure_method"] = cure_method
    call["resolved_at"] = store.clock
    touch(call)


def cure_open_calls(account, method):
    """Cure every satisfied OPEN call (creation order). Returns count."""
    cured = 0
    for call in open_calls(account["id"]):
        if call_cure_satisfied(call, account):
            resolve_call(call, "CURED", method)
            cured += 1
    if cured:
        posture_recheck(account)
    return cured


def run_call_evaluation(account):
    """Full official-basis evaluation (PRD 3.7): cure satisfied OPEN calls
    (MARKET_RECOVERY), then issue at most one new call by severity."""
    cured = cure_open_calls(account, "MARKET_RECOVERY")
    issued = None
    pending = pending_call_for_account(account)
    if pending is not None:
        issued = issue_call(account, pending[0], pending[1])
    return issued, cured


def recompute_and_evaluate(account, touch_account=True):
    """Shared cascade for official marks / policy PATCH / sweeps."""
    recompute_account(account)
    if touch_account:
        touch(account)
    return run_call_evaluation(account)


# ---------------------------------------------------------------------------
# Day trading
# ---------------------------------------------------------------------------
def day_trade_event_exists(account_id, security_id, event_date):
    return any(
        e["account_id"] == account_id and e["security_id"] == security_id
        and e["event_date"] == event_date
        for e in store.day_trade_events.values())


def record_day_trade_event(account_id, security_id, event_date):
    if day_trade_event_exists(account_id, security_id, event_date):
        return None
    event = {
        "id": new_id(),
        "account_id": account_id,
        "security_id": security_id,
        "event_date": event_date,
    }
    stamp_ledger(event)
    store.day_trade_events[event["id"]] = event
    return event


def pdt_window_dates(clock_date):
    """Trailing 5 calendar dates inclusive of the clock date (PRD 3.6)."""
    return {clock_date - timedelta(days=i) for i in range(5)}


def evaluate_pdt(account):
    """Returns "set" | "cleared" | None depending on flag transitions."""
    window = pdt_window_dates(store.clock.date())
    day_trades = sum(
        1 for f in store.fills.values()
        if f["account_id"] == account["id"] and f["is_day_trade"]
        and f["fill_date"] in window)
    fills = sum(
        1 for f in store.fills.values()
        if f["account_id"] == account["id"] and f["fill_date"] in window)
    flag = (day_trades >= PDT_MIN_DAY_TRADES
            and day_trades * 100 > PDT_RATIO_NUM * fills)
    if flag and not account["pdt_flag"]:
        account["pdt_flag"] = True
        account["pdt_flagged_at"] = store.clock
        touch(account)
        return "set"
    if not flag and account["pdt_flag"]:
        account["pdt_flag"] = False
        touch(account)
        return "cleared"
    return None


# ---------------------------------------------------------------------------
# Interest
# ---------------------------------------------------------------------------
def accrue_interest_for_account(account, today):
    """Step 1 of the daily sweep for one account: today's DAILY_ACCRUAL (one
    per account/date), then MONTHLY_POST for each prior month with unposted
    dailies. Returns (accruals_created, posts_created)."""
    accruals = 0
    posts = 0
    cash = account["cash_balance_cents"]
    debit = max(0, -cash)
    if debit > 0:
        already = any(
            e["account_id"] == account["id"] and e["entry_type"] == "DAILY_ACCRUAL"
            and e["accrual_date"] == today
            for e in store.interest_entries.values())
        if not already:
            tier = select_rate_tier(debit, today)
            if tier is not None:
                entry = {
                    "id": new_id(),
                    "account_id": account["id"],
                    "entry_type": "DAILY_ACCRUAL",
                    "accrual_date": today,
                    "debit_balance_snapshot_cents": debit,
                    "rate_bps_applied": tier["annual_rate_bps"],
                    "amount_cents": daily_accrual_amount(debit, tier["annual_rate_bps"]),
                    "posted": False,
                }
                stamp_ledger(entry)
                store.interest_entries[entry["id"]] = entry
                accruals += 1

    # Month roll: post every month strictly before the current sweep month
    # that still holds unposted dailies (chronological month order).
    current_month = month_of(today)
    by_month = {}
    for e in store.interest_entries.values():
        if (e["account_id"] == account["id"] and e["entry_type"] == "DAILY_ACCRUAL"
                and not e["posted"] and month_of(e["accrual_date"]) < current_month):
            by_month.setdefault(month_of(e["accrual_date"]), []).append(e)
    for month in sorted(by_month):
        dailies = sorted(by_month[month], key=lambda e: e["_seq"])
        total = sum(e["amount_cents"] for e in dailies)
        debit_now = max(0, -account["cash_balance_cents"])
        post = {
            "id": new_id(),
            "account_id": account["id"],
            "entry_type": "MONTHLY_POST",
            "accrual_date": today,
            "debit_balance_snapshot_cents": debit_now,
            "rate_bps_applied": dailies[-1]["rate_bps_applied"],
            "amount_cents": total,
            "posted": True,
        }
        stamp_ledger(post)
        store.interest_entries[post["id"]] = post
        for e in dailies:
            e["posted"] = True
        # The post debits cash; the recompute feeds the sweep's step 3.
        account["cash_balance_cents"] -= total
        recompute_account(account)
        touch(account)
        posts += 1
    return accruals, posts


def interest_summary(account, today):
    debit = max(0, -account["cash_balance_cents"])
    tier = select_rate_tier(debit, today) if debit > 0 else None
    current_daily = (daily_accrual_amount(debit, tier["annual_rate_bps"])
                     if tier is not None else 0)
    current_month = month_of(today)
    mtd = sum(
        e["amount_cents"] for e in store.interest_entries.values()
        if e["account_id"] == account["id"] and e["entry_type"] == "DAILY_ACCRUAL"
        and month_of(e["accrual_date"]) == current_month)
    remaining_days = days_in_month(today) - today.day
    provisional = mtd + remaining_days * current_daily
    posts = [e for e in store.interest_entries.values()
             if e["account_id"] == account["id"] and e["entry_type"] == "MONTHLY_POST"]
    posts.sort(key=lambda e: e["_seq"])
    posted_total = posts[-1]["amount_cents"] if posts else 0
    return {
        "debit_balance_cents": debit,
        "current_daily_accrual_cents": current_daily,
        "month_to_date_accrued_cents": mtd,
        "provisional_month_estimate_cents": provisional,
        "posted_month_total_cents": posted_total,
    }


# ---------------------------------------------------------------------------
# Liquidation
# ---------------------------------------------------------------------------
def non_terminal_orders_for_account(account_id):
    return [o for o in store.liquidation_orders.values()
            if o["account_id"] == account_id
            and o["order_status"] in NON_TERMINAL_ORDER_STATES]


def non_terminal_orders_for_call(call_id):
    return [o for o in store.liquidation_orders.values()
            if o["call_id"] == call_id
            and o["order_status"] in NON_TERMINAL_ORDER_STATES]


def proceeds_for_call(call_id):
    return sum(o["proceeds_cents"] for o in store.liquidation_orders.values()
               if o["call_id"] == call_id)


def liquidation_cure_satisfied(call, account):
    """LIQUIDATION_IN_PROGRESS cure test: binding official excess >= 0, or
    cumulative proceeds across the call's orders >= call_amount."""
    if binding_official_excess(account) >= 0:
        return True
    return proceeds_for_call(call["id"]) >= call["call_amount_cents"]


def after_liquidation_fill(account, call):
    """Post-fill cascade: cure the linked call (LIQUIDATION) when satisfied;
    cure any satisfied OPEN calls likewise; posture recheck."""
    if call["call_status"] == "LIQUIDATION_IN_PROGRESS" \
            and liquidation_cure_satisfied(call, account):
        resolve_call(call, "CURED", "LIQUIDATION")
    for other in open_calls(account["id"]):
        if call_cure_satisfied(other, account):
            resolve_call(other, "CURED", "LIQUIDATION")
    posture_recheck(account)


def after_liquidation_cancel(account, call):
    """When the cancellation leaves no non-terminal orders for the call and
    the cure test still fails, the call falls back to EXPIRED."""
    if call["call_status"] != "LIQUIDATION_IN_PROGRESS":
        return
    if non_terminal_orders_for_call(call["id"]):
        return
    if liquidation_cure_satisfied(call, account):
        resolve_call(call, "CURED", "LIQUIDATION")
        posture_recheck(account)
        return
    call["call_status"] = "EXPIRED"
    touch(call)
    recompute_account(account)
    touch(account)
    posture_recheck(account)
