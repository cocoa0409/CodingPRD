"""Ledger, statement, deposit, and storage-accrual calculations
(scaffold 1.3 / PRD 2.8, 3.10, 3.11)."""

from datetime import timedelta

import db
from money import (
    dec, rhu,
    DEPOSIT_PCT,
    TIER1_CENTS_PER_FT, TIER1_MAX_DAY,
    TIER2_CENTS_PER_FT, TIER2_MAX_DAY,
    TIER3_CENTS_PER_FT,
    WINTER_MULTIPLIER, NO_WINTER,
    MONTHLY_BLOCK_CENTS_PER_FT, MONTHLY_BLOCK_DAYS,
)

# Work-order states whose quoted totals count toward the deposit requirement.
DEPOSIT_WO_STATES = ("APPROVED", "IN_PROGRESS", "ON_HOLD", "COMPLETE")


def post_ledger(job_id, kind, category, amount_cents, memo=None,
                source_work_order_id=None, source_part_id=None):
    entry = {
        "id": db.new_id(),
        "job_id": job_id,
        "kind": kind,
        "category": category,
        "amount_cents": int(amount_cents),
        "memo": memo,
        "status": "POSTED",
        "source_work_order_id": source_work_order_id,
        "source_part_id": source_part_id,
        "created_at": db.now_iso(),
        "_seq": db.next_seq(),
    }
    db.ledger[entry["id"]] = entry
    return entry


def job_entries(job_id):
    return [e for e in db.ledger.values() if e["job_id"] == job_id]


def ledger_balance(job_id):
    """balance = sum(POSTED CHARGE) - sum(POSTED PAYMENT/CREDIT/DEPOSIT).
    VOIDED entries contribute nothing."""
    balance = 0
    for e in job_entries(job_id):
        if e["status"] != "POSTED":
            continue
        if e["kind"] == "CHARGE":
            balance += e["amount_cents"]
        else:
            balance -= e["amount_cents"]
    return balance


def deposit_requirement(job_id):
    """required = round_half_up(0.25 * sum(quoted_total_cents over work orders
    in {APPROVED, IN_PROGRESS, ON_HOLD, COMPLETE}))."""
    total = sum(
        w["quoted_total_cents"]
        for w in db.work_orders.values()
        if w["job_id"] == job_id and w["status"] in DEPOSIT_WO_STATES
    )
    return rhu(DEPOSIT_PCT * dec(total))


def deposits_posted(job_id):
    return sum(
        e["amount_cents"]
        for e in job_entries(job_id)
        if e["kind"] == "DEPOSIT" and e["status"] == "POSTED"
    )


def deposit_satisfied(job_id):
    """Boundary is inclusive: deposits == required exactly IS satisfied."""
    return deposits_posted(job_id) >= deposit_requirement(job_id)


def build_statement(job):
    posted = [e for e in job_entries(job["id"]) if e["status"] == "POSTED"]
    storage = sum(e["amount_cents"] for e in posted if e["kind"] == "CHARGE" and e["category"] == "STORAGE")
    labor = sum(e["amount_cents"] for e in posted if e["kind"] == "CHARGE" and e["category"] == "LABOR")
    parts = sum(e["amount_cents"] for e in posted if e["kind"] == "CHARGE" and e["category"] == "PARTS_HANDLING")
    payments = sum(e["amount_cents"] for e in posted if e["kind"] == "PAYMENT")
    credits = sum(e["amount_cents"] for e in posted if e["kind"] == "CREDIT")
    deposits = sum(e["amount_cents"] for e in posted if e["kind"] == "DEPOSIT")
    total_charges = storage + labor + parts
    required = deposit_requirement(job["id"])
    return {
        "job_id": job["id"],
        "billing_mode": job["billing_mode"],
        "status": job["status"],
        "lay_days": job["lay_days"],
        "storage_charges_cents": storage,
        "labor_charges_cents": labor,
        "parts_handling_charges_cents": parts,
        "total_charges_cents": total_charges,
        "payments_cents": payments,
        "credits_cents": credits,
        "deposits_cents": deposits,
        "balance_cents": total_charges - (payments + credits + deposits),
        "required_deposit_cents": required,
        "deposit_satisfied": deposits >= required,
    }


def _is_winter_date(d):
    """Winter window: month-day in [11-01 .. 03-31] inclusive."""
    return d.month >= 11 or d.month <= 3


def accrue_job(job, current_date):
    """Storage accrual (daily-close step 3). Walks every calendar date from
    (last_accrual_date + 1) or hauled_at through the current date inclusive.
    Same-day re-run accrues nothing. Returns the number of ledger entries
    posted for this job."""
    if job["last_accrual_date"] is not None:
        start = job["_last_accrual"] + timedelta(days=1)
    else:
        if job["hauled_at"] is None:
            return 0
        start = job["_hauled"]
    if start > current_date:
        return 0

    vessel = db.vessels.get(job["vessel_id"])
    loa = dec(vessel["loa_ft"]) if vessel is not None else dec(0)

    posted = 0
    accrued = 0
    d = start
    while d <= current_date:
        accrued += 1
        i = job["lay_days"] + accrued  # 1-based lay-day index
        if job["billing_mode"] == "MONTHLY_CONTRACT":
            if (i - 1) % MONTHLY_BLOCK_DAYS == 0:
                amount = rhu(loa * MONTHLY_BLOCK_CENTS_PER_FT)
                post_ledger(job["id"], "CHARGE", "STORAGE", amount,
                            memo=f"Storage block (lay day {i})")
                posted += 1
        else:  # DAILY
            if i <= TIER1_MAX_DAY:
                tier = TIER1_CENTS_PER_FT
            elif i <= TIER2_MAX_DAY:
                tier = TIER2_CENTS_PER_FT
            else:
                tier = TIER3_CENTS_PER_FT
            winter = WINTER_MULTIPLIER if _is_winter_date(d) else NO_WINTER
            amount = rhu(loa * tier * winter)
            post_ledger(job["id"], "CHARGE", "STORAGE", amount,
                        memo=f"Storage day {i} ({d.isoformat()})")
            posted += 1
        d += timedelta(days=1)

    if accrued > 0:
        job["lay_days"] += accrued
        job["last_accrual_date"] = current_date.isoformat()
        job["_last_accrual"] = current_date
        db.touch(job)
    return posted
