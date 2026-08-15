"""Recomputation of derived fields: room rollups, vault occupancy, statement
accrual, job accrued totals, job billing_status."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from db import store
from helpers import (
    items_of_room,
    items_of_job,
    parse_date_str,
)


def recompute_room(room):
    items = items_of_room(room["id"])
    room["item_count"] = len(items)
    if len(items) >= 1 and not any(i["condition_triage"] == "PENDING" for i in items):
        inventoried = True
    else:
        inventoried = False
    if inventoried:
        onsite = {"REGISTERED", "AWAITING_CLEANING", "IN_CLEANING", "CLEANED", "AWAITING_DISPOSAL"}
        if not any(i["processing_status"] in onsite for i in items):
            room["status"] = "CLEARED"
        else:
            room["status"] = "INVENTORIED"
    else:
        room["status"] = "OPEN"


def recompute_vault(vault):
    occupied = 0
    for p in store.placements.values():
        if p["vault_id"] == vault["id"] and p["status"] == "ACTIVE":
            item = store.items.get(p["item_id"])
            if item is not None:
                occupied += item["volume_cu_ft"]
    vault["occupied_cu_ft"] = occupied
    vault["posture"] = "FULL" if occupied == vault["capacity_cu_ft"] else "OPEN"


def recompute_subcontractor(sub):
    count = 0
    for r in store.referrals.values():
        if r["subcontractor_id"] == sub["id"] and r["status"] in ("DISPATCHED", "IN_CUSTODY", "QA_REJECTED"):
            count += 1
    sub["active_referral_count"] = count


def _months_touched(start_d, end_d):
    """Distinct calendar months touched by half-open [start_d, end_d).
    Any partial month counts as a full month."""
    if end_d <= start_d:
        return 0
    # months covered = (end.year*12+end.month) - (start.year*12+start.month) + adjustment
    # Half-open: if end_d is the 1st of a month, that month isn't touched.
    # Count distinct months of dates d with start_d <= d < end_d.
    last_d = date.fromordinal(end_d.toordinal() - 1)
    return (last_d.year - start_d.year) * 12 + (last_d.month - start_d.month) + 1


def compute_provisional_total(statement):
    """Whole-month forward-looking accrual over ACTIVE placements overlapping period."""
    job_id = statement["job_id"]
    period_start = parse_date_str(statement["period_start"])
    period_end = parse_date_str(statement["period_end"])
    total = 0
    for item in items_of_job(job_id):
        for p in store.placements.values():
            if p["item_id"] != item["id"]:
                continue
            if p["status"] != "ACTIVE":
                continue
            placed_on = parse_date_str(p["placed_on"])
            if placed_on >= period_end:
                continue
            span_start = max(placed_on, period_start)
            months = _months_touched(span_start, period_end)
            total += p["monthly_rate_cents"] * months
    return total


def compute_final_total(statement):
    """Chronological daily proration over all placements occupying >= 1 day of period."""
    job_id = statement["job_id"]
    period_start = parse_date_str(statement["period_start"])
    period_end = parse_date_str(statement["period_end"])
    total = 0
    for item in items_of_job(job_id):
        for p in store.placements.values():
            if p["item_id"] != item["id"]:
                continue
            placed_on = parse_date_str(p["placed_on"])
            if p["released_on"] is not None:
                rel = parse_date_str(p["released_on"])
                occ_end = min(rel, period_end)
            else:
                occ_end = period_end
            occ_start = max(placed_on, period_start)
            days = (occ_end - occ_start).days
            if days <= 0:
                continue
            daily = (Decimal(p["monthly_rate_cents"]) * 12 / 365).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
            total += int(daily) * days
    return total


def recompute_provisional_statements_for_job(job_id):
    """Recompute provisional_total_cents on every PROVISIONAL statement of the job."""
    for s in store.statements.values():
        if s["job_id"] == job_id and s["status"] == "PROVISIONAL":
            s["provisional_total_cents"] = compute_provisional_total(s)


def recompute_job_accrued(job):
    """accrued_storage_total_cents: provisional of PROVISIONAL + final of FINALIZED/INVOICED."""
    total = 0
    for s in store.statements.values():
        if s["job_id"] != job["id"]:
            continue
        if s["status"] == "PROVISIONAL":
            total += s["provisional_total_cents"] or 0
        elif s["status"] in ("FINALIZED", "INVOICED"):
            total += s["final_total_cents"] or 0
    job["accrued_storage_total_cents"] = total


def recompute_job_billing_status(job):
    invs = [i for i in store.invoices.values() if i["job_id"] == job["id"]]
    if any(i["status"] == "DISPUTED" for i in invs):
        job["billing_status"] = "DISPUTED"
    elif len(invs) >= 1 and all(i["status"] == "RECONCILED" for i in invs):
        job["billing_status"] = "RECONCILED"
    elif any(i["status"] in ("SUBMITTED", "RECONCILED") for i in invs):
        job["billing_status"] = "INVOICED"
    else:
        job["billing_status"] = "ACCUMULATING"


def recompute_invoice_balance(inv):
    inv["balance_cents"] = (
        inv["total_cents"] - inv["claim_credit_cents"] - inv["amount_paid_cents"]
    )


def job_rooms(job_id):
    return [r for r in store.rooms.values() if r["job_id"] == job_id]
