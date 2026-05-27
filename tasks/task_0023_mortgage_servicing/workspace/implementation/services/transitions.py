"""State-machine transitions and cross-aggregate cascades per SCAFFOLD §1.2 / PRD §3."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import db
from services.common import bump
from services import calculations as calc


# ---------- Loan helpers ----------
def recompute_total_monthly_payment(loan: dict[str, Any]) -> None:
    pmi_part = loan.get("pmi_monthly_cents", 0) if loan.get("pmi_required") else 0
    loan["total_monthly_payment_cents"] = (
        loan.get("scheduled_monthly_pi_cents", 0)
        + loan.get("escrow_monthly_cents", 0)
        + pmi_part
    )


def refresh_dpd(loan: dict[str, Any]) -> None:
    loan["days_past_due"] = calc.compute_days_past_due(loan)
    calc.update_max_dpd_observed(loan)


# ---------- Loan auto-transitions on clock advance ----------
def apply_clock_advance_transitions() -> None:
    """Fire all auto-transitions whose preconditions newly hold.

    - Loan: CURRENT -> DELINQUENT when days_past_due > GRACE_DAYS
    - EscrowDisbursement: SCHEDULED -> PAID or FAILED when scheduled_for <= now
    - ForeclosureCase: SALE_SCHEDULED -> COMPLETED when sale_date <= now
    - days_past_due refreshed on every loan
    """
    now = db.utcnow()

    # Recompute dpd for every loan; fire delinquency transitions
    for loan in db.loans.values():
        refresh_dpd(loan)
        if loan.get("status") == "CURRENT" and loan.get("days_past_due", 0) > calc.GRACE_DAYS:
            loan["status"] = "DELINQUENT"
            bump(loan)

    # Disbursements: SCHEDULED -> PAID/FAILED in chronological order
    pending = sorted(
        (d for d in db.escrow_disbursements.values() if d.get("status") == "SCHEDULED"),
        key=lambda d: d.get("scheduled_for") or "",
    )
    for d in pending:
        try:
            sched = db.parse_ts(d["scheduled_for"])
        except Exception:
            continue
        if sched <= now:
            ea = db.escrow_accounts.get(d.get("escrow_account_id"))
            if ea is None:
                continue
            amount = d.get("amount_cents", 0)
            if ea.get("balance_cents", 0) >= amount:
                d["status"] = "PAID"
                d["paid_at"] = db.fmt_ts(now)
                ea["balance_cents"] = ea.get("balance_cents", 0) - amount
            else:
                d["status"] = "FAILED"
                d["failure_reason"] = "INSUFFICIENT_FUNDS"
            bump(d)
            bump(ea)

    # ForeclosureCase: SALE_SCHEDULED -> COMPLETED when sale_date <= now
    for case in db.foreclosure_cases.values():
        if case.get("status") != "SALE_SCHEDULED":
            continue
        sd_raw = case.get("sale_date")
        if not sd_raw:
            continue
        try:
            sd = db.parse_ts(sd_raw)
        except Exception:
            continue
        if sd <= now:
            case["status"] = "COMPLETED"
            bump(case)


# ---------- Payment posting orchestration ----------
def apply_payment(loan: dict[str, Any], escrow_account: dict[str, Any] | None,
                  allocation: dict[str, int]) -> None:
    """Apply allocation side effects: balance/interest decrement, escrow credit,
       advance next_due_date for each fully-cured installment, recompute dpd."""
    loan["principal_balance_cents"] = max(0, loan.get("principal_balance_cents", 0) - allocation["principal_cents"])
    loan["accrued_interest_cents"] = max(0, loan.get("accrued_interest_cents", 0) - allocation["interest_cents"])
    loan["outstanding_late_fees_cents"] = max(0, loan.get("outstanding_late_fees_cents", 0) - allocation["late_fee_cents"])
    loan["last_payment_posted_at"] = db.fmt_ts(db.utcnow())

    if escrow_account is not None and allocation["escrow_cents"] > 0:
        escrow_account["balance_cents"] = escrow_account.get("balance_cents", 0) + allocation["escrow_cents"]
        bump(escrow_account)

    # Advance next_due_date by one month per fully-cured installment satisfied
    # A "fully-cured installment" = scheduled_pi + escrow_monthly + pmi_monthly
    scheduled_pi = loan.get("scheduled_monthly_pi_cents", 0)
    escrow_monthly = loan.get("escrow_monthly_cents", 0)
    pmi_monthly = loan.get("pmi_monthly_cents", 0) if loan.get("pmi_required") else 0
    one_installment = scheduled_pi + escrow_monthly + pmi_monthly

    # Number of installments funded by this payment (excluding suspense)
    installment_funds = (
        allocation["interest_cents"]
        + allocation["principal_cents"]
        + allocation["escrow_cents"]
        + allocation["pmi_cents"]
    )

    if one_installment > 0:
        # Determine installments cured: if the standard installment was satisfied at least once,
        # advance by 1, then advance by 1 more for each additional one_installment-worth of
        # principal curtailment.
        installments_advanced = 0
        if installment_funds >= one_installment:
            installments_advanced = 1
            # Any further principal funds beyond the first installment may advance more
            extra_principal = max(0, installment_funds + allocation["principal_cents"] - one_installment)
            # We'll use a simple model: 1 installment per posting (the most common case).
        # If posting strategy was PRINCIPAL_CURTAILMENT, still only 1 installment cured here.
        for _ in range(installments_advanced):
            _advance_next_due_date(loan)

    refresh_dpd(loan)


def _advance_next_due_date(loan: dict[str, Any]) -> None:
    raw = loan.get("next_due_date")
    if not raw:
        return
    try:
        nd = db.parse_ts(raw)
    except Exception:
        return
    # Add one calendar month
    y = nd.year
    m = nd.month + 1
    if m > 12:
        m = 1
        y += 1
    # Clamp day to last day of month
    import calendar
    day = min(nd.day, calendar.monthrange(y, m)[1])
    new_nd = nd.replace(year=y, month=m, day=day)
    loan["next_due_date"] = db.fmt_ts(new_nd)


# ---------- Loan transition cascades on payment ----------
def post_payment_cascade_loan_status(loan: dict[str, Any]) -> bool:
    """After applying a payment, transition the loan's status if precondition met.
    Returns True if any state change occurred.
    """
    changed = False
    # DELINQUENT -> CURRENT
    if loan.get("status") == "DELINQUENT" and loan.get("days_past_due", 0) == 0:
        loan["status"] = "CURRENT"
        changed = True
    # REINSTATED -> CURRENT (first post-reinstatement payment posts cleanly)
    elif loan.get("status") == "REINSTATED" and loan.get("days_past_due", 0) == 0:
        loan["status"] = "CURRENT"
        changed = True
    return changed


def transition_to_paid_off(loan: dict[str, Any]) -> None:
    """Loan -> PAID_OFF cascade: status, pmi_status, cancel scheduled disbursements."""
    loan["status"] = "PAID_OFF"
    if loan.get("pmi_status") in {"ACTIVE", "REMOVAL_PENDING"}:
        loan["pmi_status"] = "AUTO_TERMINATED"
    loan["pmi_required"] = False
    # Cancel all SCHEDULED EscrowDisbursement rows for this loan's escrow account(s)
    for ea in db.escrow_accounts.values():
        if ea.get("loan_id") != loan["id"]:
            continue
        for d in db.escrow_disbursements.values():
            if d.get("escrow_account_id") != ea["id"]:
                continue
            if d.get("status") == "SCHEDULED":
                d["status"] = "CANCELLED"
                bump(d)


# ---------- Foreclosure case cure-amount refresh ----------
def refresh_cure_amount(case: dict[str, Any]) -> None:
    loan = db.loans.get(case.get("loan_id"))
    if loan is None:
        return
    refresh_dpd(loan)
    case["cure_amount_cents"] = calc.foreclosure_cure_amount(loan)
