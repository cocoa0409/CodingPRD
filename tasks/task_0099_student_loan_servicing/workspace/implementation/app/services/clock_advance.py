"""Orchestrate /_clock/advance side effects: interest accrual, grace exit,
delinquency aging, auto-default, hardship auto-exit, rehab completion."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..clock import (
    CLOCK,
    add_days,
    days_between,
    first_of_month_at_or_after,
    format_iso,
    parse_iso,
)
from ..store import bump_version, common_fields_append_only, get_store, now_iso
from . import calculations as calc
from . import loans as loan_svc
from .borrowers import recompute_aggregates, loans_for_borrower


def advance_clock(new_now: datetime) -> None:
    """Set the clock and run every chronological side-effect cascade."""
    old_now = CLOCK.now
    # If going backwards, don't accrue or fire cascades; just set.
    if new_now <= old_now:
        CLOCK.set(new_now)
        _recompute_all_aggregates()
        return
    CLOCK.set(new_now)
    # Now run cascades. Use new_now for the "now" reference but the loans'
    # last_accrual_at to determine elapsed days.
    _accrue_all_loans(new_now)
    _process_time_gated_transitions(new_now)
    _recompute_all_aggregates()


def _accrue_all_loans(new_now: datetime) -> None:
    for loan in list(get_store().loans.values()):
        if loan["status"] in ("PAID_OFF", "DISCHARGED", "IN_SCHOOL"):
            continue
        try:
            last = parse_iso(loan["last_accrual_at"])
        except Exception:
            continue
        elapsed = days_between(new_now, last)
        if elapsed <= 0:
            continue
        added = calc.accrue_interest_for_loan(loan, elapsed)
        loan["last_accrual_at"] = format_iso(new_now)
        if added > 0:
            bump_version(loan)


def _process_time_gated_transitions(new_now: datetime) -> None:
    store = get_store()
    # GRACE -> REPAYMENT after 180 days
    for loan in list(store.loans.values()):
        if loan["status"] != "GRACE":
            continue
        try:
            entered = parse_iso(loan["status_entered_at"])
        except Exception:
            continue
        if days_between(new_now, entered) >= 180:
            # Capitalize accrued on unsubsidized + plus
            if loan["loan_type"] in ("DIRECT_UNSUBSIDIZED", "DIRECT_PLUS"):
                loan_svc.capitalize_accrued(loan)
            else:
                loan["accrued_interest_cents"] = 0
            loan_svc.set_status(loan, "REPAYMENT")
            loan_svc.set_due_first_of_month(loan, new_now)
            bump_version(loan)

    # DEFERMENT / FORBEARANCE auto-exit on requested_to
    _auto_exit_hardship(new_now)

    # REPAYMENT -> DELINQUENT (days_past_due >= 1)
    for loan in list(store.loans.values()):
        if loan["status"] not in ("REPAYMENT", "DELINQUENT"):
            continue
        ldue = loan.get("last_payment_due_at")
        if not ldue:
            continue
        try:
            due_dt = parse_iso(ldue)
        except Exception:
            continue
        days_overdue = days_between(new_now, due_dt)
        if days_overdue >= 1:
            loan["days_past_due"] = days_overdue
            if loan["status"] == "REPAYMENT":
                loan_svc.set_status(loan, "DELINQUENT")
        else:
            # not past due
            if loan["status"] == "DELINQUENT":
                # not curing automatically; leave status
                pass

    # DELINQUENT -> DEFAULT (days_past_due >= 270)
    for loan in list(store.loans.values()):
        if loan["status"] != "DELINQUENT":
            continue
        if int(loan.get("days_past_due", 0)) >= 270:
            _declare_default(loan)

    # REHAB completion: 9 REHAB_PAYMENT_RECORDED actions within last 10 months
    for loan in list(store.loans.values()):
        if loan["status"] != "REHABILITATION":
            continue
        actions = [
            a
            for a in store.collections_actions.values()
            if a.get("loan_id") == loan["id"] and a.get("kind") == "REHAB_PAYMENT_RECORDED"
        ]
        # within last 10 months ~ 304 days
        window_start = new_now - timedelta(days=304)
        recent = [a for a in actions if parse_iso(a["occurred_at"]) >= window_start]
        if len(recent) >= 9:
            # append REHAB_COMPLETED action
            completion = {
                **common_fields_append_only(),
                "borrower_id": loan["borrower_id"],
                "loan_id": loan["id"],
                "kind": "REHAB_COMPLETED",
                "amount_cents": 0,
                "occurred_at": format_iso(new_now),
                "recorded_by": "system",
            }
            store.collections_actions[completion["id"]] = completion
            loan["days_past_due"] = 0
            loan_svc.set_status(loan, "REPAYMENT")
            loan_svc.set_due_first_of_month(loan, new_now)
            bump_version(loan)


def _auto_exit_hardship(new_now: datetime) -> None:
    store = get_store()
    # Find APPROVED hardship requests whose requested_to <= now
    for req in list(store.hardship_requests.values()):
        if req.get("status") != "APPROVED":
            continue
        try:
            rto = parse_iso(req["requested_to"])
        except Exception:
            continue
        if rto > new_now:
            continue
        # auto-exit each loan referenced by this request that is still in
        # DEFERMENT or FORBEARANCE (and belongs to this request's borrower).
        for lid in req.get("applied_loan_ids", []):
            loan = store.loans.get(lid)
            if not loan:
                continue
            if loan["status"] == "DEFERMENT":
                if loan["loan_type"] in ("DIRECT_UNSUBSIDIZED", "DIRECT_PLUS"):
                    loan_svc.capitalize_accrued(loan)
                else:
                    loan["accrued_interest_cents"] = 0
                loan_svc.set_status(loan, "REPAYMENT")
                loan_svc.set_due_first_of_month(loan, new_now)
                bump_version(loan)
            elif loan["status"] == "FORBEARANCE":
                loan_svc.capitalize_accrued(loan)
                loan_svc.set_status(loan, "REPAYMENT")
                loan_svc.set_due_first_of_month(loan, new_now)
                bump_version(loan)


def _declare_default(loan: dict[str, Any]) -> None:
    """Loan DELINQUENT -> DEFAULT. Side effects per §3.6."""
    store = get_store()
    loan_svc.capitalize_accrued(loan)
    loan_svc.set_status(loan, "DEFAULT")
    # Append DEFAULT_DECLARATION
    action = {
        **common_fields_append_only(),
        "borrower_id": loan["borrower_id"],
        "loan_id": loan["id"],
        "kind": "DEFAULT_DECLARATION",
        "amount_cents": 0,
        "occurred_at": now_iso(),
        "recorded_by": "system",
    }
    store.collections_actions[action["id"]] = action
    # Cascade: any ACTIVE plan covering this loan -> TERMINATED
    affected_plans = [
        p
        for p in store.plans.values()
        if p.get("status") == "ACTIVE"
        and loan["id"] in p.get("included_loan_ids", [])
    ]
    for plan in affected_plans:
        plan["status"] = "TERMINATED"
        bump_version(plan)
        # All non-defaulted loans in this plan move to REPAYMENT.
        for lid in plan.get("included_loan_ids", []):
            if lid == loan["id"]:
                continue
            other = store.loans.get(lid)
            if not other:
                continue
            if other["status"] in ("DEFAULT", "PAID_OFF", "DISCHARGED"):
                continue
            loan_svc.set_status(other, "REPAYMENT")
            loan_svc.set_due_first_of_month(other, CLOCK.now)
            bump_version(other)


def _recompute_all_aggregates() -> None:
    for b in get_store().borrowers.values():
        recompute_aggregates(b)
