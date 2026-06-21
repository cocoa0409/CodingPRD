"""Lifecycle cascades: election -> enrollment+account, terminations, HIPAA
certificate minting, and the per-plan clock sweep.

Implements PRD §3.3, §3.4, §3.8, §3.9, §3.10.
"""
from db import store
from errors import ApiError
from models import touch, _cert_common, CERTIFICATE_FIELDS  # noqa: F401
from timeutil import (
    add_days, add_months, parse_year_month, year_month_index,
    last_day_of_month, month_diff_inclusive,
)
from services.ledger import monthly_premium_cents, recompute_account


# ---------------------------------------------------------------------------
# Helpers shared by terminations
# ---------------------------------------------------------------------------
def _account_for_enrollment(enrollment_id):
    for acc in store.accounts.values():
        if acc["enrollment_id"] == enrollment_id:
            return acc
    return None


def _void_open_invoices_after(account_id, boundary_dt):
    """VOID every OPEN invoice whose coverage_month is strictly after the month
    of boundary_dt. boundary_dt None => void all OPEN invoices."""
    for inv in store.invoices.values():
        if inv["account_id"] != account_id:
            continue
        if inv["status"] != "OPEN":
            continue
        if boundary_dt is None:
            inv["status"] = "VOID"
            touch(inv)
            continue
        y, m = parse_year_month(inv["coverage_month"])
        if year_month_index(y, m) > year_month_index(boundary_dt.year, boundary_dt.month):
            inv["status"] = "VOID"
            touch(inv)


def _void_all_open_invoices(account_id):
    for inv in store.invoices.values():
        if inv["account_id"] == account_id and inv["status"] == "OPEN":
            inv["status"] = "VOID"
            touch(inv)


def mint_certificate(enrollment, coverage_from, coverage_through, reason):
    """Create a HIPAA certificate spanning [coverage_from, coverage_through].
    No certificate when through < from (creditable_months would be 0)."""
    if coverage_through < coverage_from:
        return None
    creditable = month_diff_inclusive(coverage_from, coverage_through)
    cert = {
        "beneficiary_id": enrollment["beneficiary_id"],
        "enrollment_id": enrollment["id"],
        "coverage_from": coverage_from,
        "coverage_through": coverage_through,
        "creditable_months": creditable,
        "issued_reason": reason,
    }
    _cert_common(cert)
    store.certificates[cert["id"]] = cert
    return cert


def _end_beneficiary(beneficiary_id):
    ben = store.beneficiaries.get(beneficiary_id)
    if ben is not None and ben.get("status") != "COVERAGE_ENDED":
        ben["status"] = "COVERAGE_ENDED"
        touch(ben)


# ---------------------------------------------------------------------------
# Election cascade (PRD §3.4) — depth-3
# ---------------------------------------------------------------------------
def perform_election(notice, event, plan, beneficiary):
    """Notice OUTSTANDING -> ELECTED; create CobraEnrollment + PremiumAccount;
    event -> ELECTED, version++; beneficiary -> COBRA_ENROLLED. Returns the
    enrollment."""
    now = store.now()

    notice["status"] = "ELECTED"
    touch(notice)

    coverage_start = event["coverage_loss_date"]
    base_max = event["max_coverage_months"]
    extension_months = 0
    scheduled_end = add_days(add_months(coverage_start, base_max + extension_months), -1)

    enrollment = {
        "notice_id": notice["id"],
        "beneficiary_id": beneficiary["id"],
        "event_id": event["id"],
        "elected_at": now,
        "coverage_start_date": coverage_start,
        "base_max_months": base_max,
        "extension_months": extension_months,
        "scheduled_end_date": scheduled_end,
        "disability_extension": False,
        "actual_end_date": None,
        "termination_reason": None,
        "status": "PENDING_INITIAL_PREMIUM",
    }
    from models import _common
    _common(enrollment)
    store.enrollments[enrollment["id"]] = enrollment

    account = {
        "enrollment_id": enrollment["id"],
        "beneficiary_id": beneficiary["id"],
        "monthly_premium_cents": monthly_premium_cents(plan),
        "amount_invoiced_cents": 0,
        "amount_paid_cents": 0,
        "amount_subsidized_cents": 0,
        "amount_refunded_cents": 0,
        "credit_balance_cents": 0,
        "paid_through_date": None,
        "initial_premium_due_date": add_days(now, plan["initial_premium_grace_days"]),
    }
    _common(account)
    store.accounts[account["id"]] = account

    # event -> ELECTED, version++
    event["status"] = "ELECTED"
    touch(event)

    # beneficiary -> COBRA_ENROLLED
    beneficiary["status"] = "COBRA_ENROLLED"
    touch(beneficiary)

    return enrollment


# ---------------------------------------------------------------------------
# Payment-driven vesting (PENDING_INITIAL_PREMIUM -> ACTIVE) (PRD §3.6)
# ---------------------------------------------------------------------------
def maybe_vest_enrollment(enrollment, account):
    """If enrollment is PENDING_INITIAL_PREMIUM and month 1 is now satisfied
    with the satisfying payment received on/before initial_premium_due_date,
    flip to ACTIVE. The latest month-1 payment's received_date is the anchor."""
    if enrollment["status"] != "PENDING_INITIAL_PREMIUM":
        return
    from services.ledger import invoice_for_month, month_satisfied
    start = enrollment["coverage_start_date"]
    month1 = "%04d-%02d" % (start.year, start.month)
    inv = invoice_for_month(account["id"], month1)
    if inv is None:
        return
    if not month_satisfied(account["id"], inv):
        return
    # The satisfying payment must be received on or before the initial premium
    # due date. Use the latest POSTED month-1 payment as the satisfying anchor.
    candidates = [p for p in store.payments.values()
                  if p["account_id"] == account["id"]
                  and p["status"] == "POSTED"
                  and p["target_coverage_month"] == month1]
    if not candidates:
        return
    candidates.sort(key=lambda p: (p["received_date"], p["_seq"]))
    satisfying = candidates[-1]
    if satisfying["received_date"] > account["initial_premium_due_date"]:
        return
    enrollment["status"] = "ACTIVE"
    touch(enrollment)


# ---------------------------------------------------------------------------
# Early termination (PRD §3.9)
# ---------------------------------------------------------------------------
def terminate_early(enrollment, reason):
    now = store.now()
    account = _account_for_enrollment(enrollment["id"])
    enrollment["status"] = "TERMINATED"
    enrollment["termination_reason"] = reason
    enrollment["actual_end_date"] = now
    touch(enrollment)

    if account is not None:
        _void_open_invoices_after(account["id"], now)
        recompute_account(account, enrollment)

    _end_beneficiary(enrollment["beneficiary_id"])
    mint_certificate(enrollment, enrollment["coverage_start_date"], now, reason)

    if reason == "PLAN_TERMINATED":
        plan = _plan_for_enrollment(enrollment)
        if plan is not None and plan.get("status") != "TERMINATED":
            plan["status"] = "TERMINATED"
            touch(plan)


def _plan_for_enrollment(enrollment):
    ben = store.beneficiaries.get(enrollment["beneficiary_id"])
    if ben is None:
        return None
    return store.plans.get(ben["plan_id"])


# ---------------------------------------------------------------------------
# Disability extension (PRD §3.8)
# ---------------------------------------------------------------------------
def apply_disability_extension(enrollment):
    enrollment["extension_months"] = 11
    enrollment["disability_extension"] = True
    coverage_start = enrollment["coverage_start_date"]
    enrollment["scheduled_end_date"] = add_days(add_months(coverage_start, 29), -1)
    touch(enrollment)


# ---------------------------------------------------------------------------
# Clock sweep (PRD §3.10 + §3.4 lapse)
# ---------------------------------------------------------------------------
def run_sweep(plan):
    now = store.now()
    plan_id = plan["id"]

    # Beneficiaries / events / notices belonging to this plan.
    plan_beneficiary_ids = {b["id"] for b in store.beneficiaries.values()
                            if b["plan_id"] == plan_id}

    # 1. Expire OUTSTANDING notices past election_deadline -> event LAPSED,
    #    beneficiary COVERAGE_ENDED.
    for notice in store.notices.values():
        if notice["status"] != "OUTSTANDING":
            continue
        if notice["beneficiary_id"] not in plan_beneficiary_ids:
            continue
        if now > notice["election_deadline"]:
            notice["status"] = "EXPIRED"
            touch(notice)
            event = store.events.get(notice["event_id"])
            if event is not None and event["status"] == "NOTICE_SENT":
                event["status"] = "LAPSED"
                touch(event)
            _end_beneficiary(notice["beneficiary_id"])

    # 2/3/4. Enrollment sweeps.
    for enrollment in store.enrollments.values():
        if enrollment["beneficiary_id"] not in plan_beneficiary_ids:
            continue
        if enrollment["status"] == "PENDING_INITIAL_PREMIUM":
            _sweep_pending(enrollment, now)
        elif enrollment["status"] == "ACTIVE":
            _sweep_active(enrollment, plan, now)


def _sweep_pending(enrollment, now):
    """PENDING_INITIAL_PREMIUM past initial_premium_due_date with month 1
    unsatisfied -> TERMINATED (NONPAYMENT), actual_end = coverage_start - 1 day,
    VOID all OPEN invoices, beneficiary COVERAGE_ENDED. No certificate."""
    from services.ledger import invoice_for_month, month_satisfied
    account = _account_for_enrollment(enrollment["id"])
    if account is None:
        return
    if now <= account["initial_premium_due_date"]:
        return
    start = enrollment["coverage_start_date"]
    month1 = "%04d-%02d" % (start.year, start.month)
    inv = invoice_for_month(account["id"], month1)
    satisfied = inv is not None and month_satisfied(account["id"], inv)
    if satisfied:
        return
    enrollment["status"] = "TERMINATED"
    enrollment["termination_reason"] = "NONPAYMENT"
    enrollment["actual_end_date"] = add_days(start, -1)
    touch(enrollment)
    _void_all_open_invoices(account["id"])
    recompute_account(account, enrollment)
    _end_beneficiary(enrollment["beneficiary_id"])
    # No HIPAA certificate (creditable_months would be 0).


def _sweep_active(enrollment, plan, now):
    """ACTIVE enrollment: check recurring-grace nonpayment first, then
    run-to-term."""
    account = _account_for_enrollment(enrollment["id"])

    # 3a. Recurring-grace nonpayment: earliest unsatisfied OPEN month past its
    #     recurring grace (first-of-month + recurring_premium_grace_days).
    if account is not None:
        overdue = _earliest_overdue_month(account, enrollment, plan, now)
        if overdue is not None:
            ptd = account.get("paid_through_date")
            if ptd is None:
                # No vested month; coverage never advanced past month 1. Treat
                # actual_end as coverage_start - 1 day (no creditable coverage).
                actual_end = add_days(enrollment["coverage_start_date"], -1)
            else:
                actual_end = ptd
            enrollment["status"] = "TERMINATED"
            enrollment["termination_reason"] = "NONPAYMENT"
            enrollment["actual_end_date"] = actual_end
            touch(enrollment)
            _void_open_invoices_after(account["id"], ptd)
            recompute_account(account, enrollment)
            _end_beneficiary(enrollment["beneficiary_id"])
            mint_certificate(enrollment, enrollment["coverage_start_date"],
                             actual_end, "NONPAYMENT")
            return

    # 3b. Run-to-term: clock past scheduled_end_date.
    if now > enrollment["scheduled_end_date"]:
        enrollment["status"] = "TERMINATED"
        enrollment["termination_reason"] = "RUN_TO_TERM"
        enrollment["actual_end_date"] = enrollment["scheduled_end_date"]
        touch(enrollment)
        _end_beneficiary(enrollment["beneficiary_id"])
        mint_certificate(enrollment, enrollment["coverage_start_date"],
                         enrollment["scheduled_end_date"], "RUN_TO_TERM")


def _earliest_overdue_month(account, enrollment, plan, now):
    """Return the datetime (first-of-month) of the earliest OPEN, unsatisfied
    coverage month whose recurring grace (first-of-month +
    recurring_premium_grace_days) has passed; else None.

    Walks OPEN invoices in ascending coverage_month_index."""
    from services.ledger import month_satisfied
    invoices = [inv for inv in store.invoices.values()
                if inv["account_id"] == account["id"] and inv["status"] == "OPEN"]
    invoices.sort(key=lambda inv: inv["coverage_month_index"])
    for inv in invoices:
        if month_satisfied(account["id"], inv):
            continue
        y, m = parse_year_month(inv["coverage_month"])
        from datetime import datetime, timezone
        first_of_month = datetime(y, m, 1, tzinfo=timezone.utc)
        grace_end = add_days(first_of_month, plan["recurring_premium_grace_days"])
        if now > grace_end:
            return first_of_month
        # Earliest unsatisfied month not yet past grace: stop (no later month
        # can be "earliest unsatisfied").
        return None
    return None
