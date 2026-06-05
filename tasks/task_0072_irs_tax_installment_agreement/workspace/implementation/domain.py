from datetime import timedelta

import calc
from common import iso, make_record, touch
from db import store, clock


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def ser_account(a):
    return {
        "id": a["id"],
        "taxpayer_name": a["taxpayer_name"],
        "tin": a["tin"],
        "filing_status": a["filing_status"],
        "monthly_disposable_income_cents": a["monthly_disposable_income_cents"],
        "collection_status": a["collection_status"],
        "total_balance_cents": a["total_balance_cents"],
        "csed_protection_count": a["csed_protection_count"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_period(p):
    return {
        "id": p["id"],
        "tax_account_id": p["tax_account_id"],
        "tax_year": p["tax_year"],
        "assessed_tax_cents": p["assessed_tax_cents"],
        "assessment_date": iso(p["assessment_date"]),
        "csed_date": iso(p["csed_date"]),
        "penalty_accrued_cents": p["penalty_accrued_cents"],
        "interest_accrued_cents": p["interest_accrued_cents"],
        "balance_due_cents": p["balance_due_cents"],
        "paid_to_principal_cents": p["paid_to_principal_cents"],
        "period_status": p["period_status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_suspension(s):
    return {
        "id": s["id"],
        "tax_period_id": s["tax_period_id"],
        "reason": s["reason"],
        "start_at": iso(s["start_at"]),
        "end_at": iso(s["end_at"]),
        "days_counted": s["days_counted"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_agreement(g):
    return {
        "id": g["id"],
        "tax_account_id": g["tax_account_id"],
        "active_from": iso(g["active_from"]),
        "active_to": iso(g["active_to"]),
        "agreement_type": g["agreement_type"],
        "payment_method": g["payment_method"],
        "monthly_payment_cents": g["monthly_payment_cents"],
        "setup_fee_cents": g["setup_fee_cents"],
        "low_income_flag": g["low_income_flag"],
        "term_months": g["term_months"],
        "status": g["status"],
        "approved_by_user_id": g["approved_by_user_id"],
        "missed_debit_count": g["missed_debit_count"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def ser_payment(p):
    return {
        "id": p["id"],
        "tax_account_id": p["tax_account_id"],
        "tax_period_id": p["tax_period_id"],
        "amount_cents": p["amount_cents"],
        "payment_source": p["payment_source"],
        "posted_at": iso(p["posted_at"]),
        "created_at": p["created_at"],
    }


def ser_offer(o):
    return {
        "id": o["id"],
        "tax_account_id": o["tax_account_id"],
        "offer_amount_cents": o["offer_amount_cents"],
        "rcp_cents": o["rcp_cents"],
        "net_realizable_equity_cents": o["net_realizable_equity_cents"],
        "status": o["status"],
        "submitted_by_user_id": o["submitted_by_user_id"],
        "accepted_by_user_id": o["accepted_by_user_id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_lien(l):
    return {
        "id": l["id"],
        "tax_account_id": l["tax_account_id"],
        "filed_amount_cents": l["filed_amount_cents"],
        "status": l["status"],
        "released_at": iso(l["released_at"]),
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ser_cnc(c):
    return {
        "id": c["id"],
        "tax_account_id": c["tax_account_id"],
        "hardship_reason": c["hardship_reason"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_event(e):
    return {
        "id": e["id"],
        "tax_account_id": e["tax_account_id"],
        "event_type": e["event_type"],
        "tax_period_id": e["tax_period_id"],
        "suspension_days": e["suspension_days"],
        "created_at": e["created_at"],
    }


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def periods_of(account_id):
    return [p for p in store.tax_periods.values() if p["tax_account_id"] == account_id]


def agreements_of(account_id):
    return [g for g in store.installment_agreements.values()
            if g["tax_account_id"] == account_id]


def offers_of(account_id):
    return [o for o in store.offers.values() if o["tax_account_id"] == account_id]


def cncs_of(account_id):
    return [c for c in store.cnc_determinations.values()
            if c["tax_account_id"] == account_id]


def open_suspensions_of_period(period_id):
    return [s for s in store.csed_suspensions.values()
            if s["tax_period_id"] == period_id and s["end_at"] is None]


# ---------------------------------------------------------------------------
# Account events
# ---------------------------------------------------------------------------

def append_event(account_id, event_type, period_id=None, suspension_days=0):
    rec = make_record(versioned=False)
    rec["tax_account_id"] = account_id
    rec["event_type"] = event_type
    rec["tax_period_id"] = period_id
    rec["suspension_days"] = suspension_days
    store.account_events[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Active DDIA detection (for penalty rate selection)
# ---------------------------------------------------------------------------

def has_active_ddia(account_id):
    for g in agreements_of(account_id):
        if g["payment_method"] == "DIRECT_DEBIT" and g["status"] in (
                "APPROVED", "REINSTATED"):
            return True
    return False


# ---------------------------------------------------------------------------
# CSED date recompute (event-sourced from closed suspension days)
# ---------------------------------------------------------------------------

def recompute_csed_date(period):
    base = period["assessment_date"] + timedelta(days=calc.CSED_BASE_DAYS)
    suspended = 0
    for e in store.account_events.values():
        if (e["event_type"] == "CSED_SUSPEND_END"
                and e["tax_period_id"] == period["id"]):
            suspended += e["suspension_days"]
    period["csed_date"] = base + timedelta(days=suspended)


# ---------------------------------------------------------------------------
# Penalty / interest / balance recompute
# ---------------------------------------------------------------------------

def recompute_period_financials(period, account_id):
    now = clock.now()
    months = calc.full_calendar_months(period["assessment_date"], now)
    ddia = has_active_ddia(account_id)
    penalty = calc.accrued_penalty_cents(period["assessed_tax_cents"], months, ddia)
    interest = calc.accrued_interest_cents(period["assessed_tax_cents"], months)
    period["penalty_accrued_cents"] = penalty
    period["interest_accrued_cents"] = interest
    gross = period["assessed_tax_cents"] + penalty + interest
    balance = gross - period["paid_to_principal_cents"]
    period["balance_due_cents"] = max(0, balance)


def recompute_account_balance(account):
    total = 0
    for p in periods_of(account["id"]):
        if p["period_status"] in ("ASSESSED", "IN_COLLECTION"):
            total += p["balance_due_cents"]
    account["total_balance_cents"] = total


def derive_collection_status(account):
    if account["total_balance_cents"] == 0:
        return "RESOLVED"
    for c in cncs_of(account["id"]):
        if c["status"] == "ACTIVE":
            return "CNC"
    for o in offers_of(account["id"]):
        if o["status"] in ("SUBMITTED", "EVALUATING"):
            return "OIC_PENDING"
    for g in agreements_of(account["id"]):
        if g["status"] == "APPROVED":
            return "IN_AGREEMENT"
    return "ACTIVE_COLLECTION"


def reconcile_account(account):
    """Recompute total balance + collection status and bump version/updated_at."""
    recompute_account_balance(account)
    account["collection_status"] = derive_collection_status(account)
    touch(account)


def reconcile_account_no_touch(account):
    recompute_account_balance(account)
    account["collection_status"] = derive_collection_status(account)


# ---------------------------------------------------------------------------
# Period state transition on payment / agreement
# ---------------------------------------------------------------------------

def maybe_satisfy_period(period):
    if period["period_status"] == "IN_COLLECTION" and period["balance_due_cents"] == 0:
        period["period_status"] = "SATISFIED"
        touch(period)


# ---------------------------------------------------------------------------
# CSED suspension open/close (automatic, as side effects)
# ---------------------------------------------------------------------------

def open_suspension(period, reason, account):
    rec = make_record(versioned=True)
    rec["tax_period_id"] = period["id"]
    rec["reason"] = reason
    rec["start_at"] = clock.now()
    rec["end_at"] = None
    rec["days_counted"] = 0
    store.csed_suspensions[rec["id"]] = rec
    account["csed_protection_count"] += 1
    append_event(account["id"], "CSED_SUSPEND_START", period_id=period["id"])
    return rec


def close_suspension(susp, end_at, account):
    susp["end_at"] = end_at
    days = (end_at - susp["start_at"]).days
    if days < 0:
        days = 0
    susp["days_counted"] = days
    touch(susp)
    account["csed_protection_count"] = max(0, account["csed_protection_count"] - 1)
    period = store.tax_periods.get(susp["tax_period_id"])
    append_event(account["id"], "CSED_SUSPEND_END",
                 period_id=susp["tax_period_id"], suspension_days=days)
    if period is not None:
        recompute_csed_date(period)
        touch(period)


def close_all_open_suspensions(account):
    now = clock.now()
    for p in periods_of(account["id"]):
        for s in open_suspensions_of_period(p["id"]):
            close_suspension(s, now, account)


# ---------------------------------------------------------------------------
# Agreement auto-close when balance hits 0
# ---------------------------------------------------------------------------

def maybe_autoclose_agreements(account):
    if account["total_balance_cents"] != 0:
        return
    for g in agreements_of(account["id"]):
        if g["status"] in ("APPROVED", "REINSTATED"):
            g["status"] = "CLOSED"
            close_all_open_suspensions(account)
            touch(g)
