"""Calculation rules: budget_allocation, fiduciary_fee, spend_down_excess,
report_totals, bond_utilization."""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
from services.cascade import clock_month_str
from services.derived import recompute_bond_rollups


CANONICAL_CATEGORY_ORDER = ["HOUSING", "FOOD", "CLOTHING", "PERSONAL", "MEDICAL", "EDUCATION", "SAVINGS"]


# --- budget_allocation ---------------------------------------------------

def compute_allocated_lines(source_benefit_cents, lines):
    """lines: list of {category, percent} — returns list of {category, amount_cents}."""
    allocated = []
    for line in lines:
        raw = (Decimal(source_benefit_cents) * Decimal(line["percent"])) / Decimal(100)
        amt = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        allocated.append({"category": line["category"], "amount_cents": amt})
    total_allocated = sum(a["amount_cents"] for a in allocated)
    residual = source_benefit_cents - total_allocated
    if residual != 0 and allocated:
        # fold into HOUSING if present else first in canonical order
        by_cat = {a["category"]: a for a in allocated}
        target = None
        if "HOUSING" in by_cat:
            target = by_cat["HOUSING"]
        else:
            for cat in CANONICAL_CATEGORY_ORDER:
                if cat in by_cat:
                    target = by_cat[cat]
                    break
        if target is not None:
            target["amount_cents"] += residual
    return allocated


# --- fiduciary_fee -------------------------------------------------------

TIER1_LIMIT = 100000
TIER1_RATE = Decimal("0.05")
TIER2_LIMIT = 300000
TIER2_RATE = Decimal("0.03")
TIER3_RATE = Decimal("0.015")
MONTHLY_CAP = 20000


def compute_fiduciary_fee(client_id, amount_cents, release_clock_dt):
    """Marginal tier fee on the disbursement, positioned by month-to-date
    released volume strictly before this release. Returns integer cents."""
    release_month = f"{release_clock_dt.year:04d}-{release_clock_dt.month:02d}"

    v = 0
    accrued = 0
    for d in store.disbursements.values():
        if d["client_id"] != client_id:
            continue
        if d["status"] not in ("RELEASED", "RETURNED"):
            continue
        ra = d.get("released_at")
        if not ra:
            continue
        ra_month = ra[:7]  # ISO "YYYY-MM..."
        if ra_month != release_month:
            continue
        v += d["amount_cents"]
        accrued += d.get("fee_cents", 0)

    v_dec = Decimal(v)
    amt_dec = Decimal(amount_cents)

    tier1 = (min(v_dec + amt_dec, Decimal(TIER1_LIMIT)) - min(v_dec, Decimal(TIER1_LIMIT))) * TIER1_RATE
    tier2 = (min(max(v_dec + amt_dec, Decimal(TIER1_LIMIT)), Decimal(TIER2_LIMIT))
             - min(max(v_dec, Decimal(TIER1_LIMIT)), Decimal(TIER2_LIMIT))) * TIER2_RATE
    tier3 = max(Decimal(0), (v_dec + amt_dec) - Decimal(TIER2_LIMIT)) * TIER3_RATE
    raw = tier1 + tier2 + tier3
    rounded = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    headroom = max(0, MONTHLY_CAP - accrued)
    return min(rounded, headroom)


# --- spend_down_excess ---------------------------------------------------

def _month_bounds(yyyymm):
    y, m = yyyymm.split("-")
    y, m = int(y), int(m)
    first = date(y, m, 1)
    if m == 12:
        last = date(y, 12, 31)
    else:
        last = date(y, m + 1, 1) - timedelta(days=1)
    return first, last


def entitlement_window_covers_month(ent, target_month):
    """True if entitlement's [start, end) window covers any day of target_month."""
    first, last = _month_bounds(target_month)
    start = ent["effective_start_date"]
    end = ent["effective_end_date"]  # may be None
    # window [start, end); covers month iff start <= last AND (end is None OR end > first)
    if start > last:
        return False
    if end is None:
        return True
    return end > first


def compute_provisional_excess(client, target_month):
    expected_inflow = 0
    for e in store.entitlements.values():
        if e["client_id"] != client["id"]:
            continue
        if e["status"] != "VERIFIED":
            continue
        if entitlement_window_covers_month(e, target_month):
            expected_inflow += e["monthly_benefit_cents"]
    countable = client.get("countable_resources_cents", 0)
    limit = client.get("medicaid_resource_limit_cents") or 200000
    return max(0, countable + expected_inflow - limit)


def compute_final_excess(client):
    countable = client.get("countable_resources_cents", 0)
    limit = client.get("medicaid_resource_limit_cents") or 200000
    return max(0, countable - limit)


# --- report_totals -------------------------------------------------------

def compute_opening_balance(client_id, period_start):
    """Sum ledger amount_cents over all client accounts with created_at < period_start."""
    total = 0
    account_ids = {a["id"] for a in store.accounts.values() if a["client_id"] == client_id}
    for eid in store.ledger_order:
        e = store.ledger_entries[eid]
        if e["account_id"] not in account_ids:
            continue
        # e["created_at"] is ISO string; compare date portion
        entry_date_str = e["created_at"][:10]
        if entry_date_str < period_start.isoformat():
            total += e["amount_cents"]
    return total


def compute_report_totals(report):
    """Compute (receipts, disbursements, opening, ending) per basis variant."""
    client_id = report["client_id"]
    ps = report["period_start_date"]
    pe = report["period_end_date"]
    basis = report["basis"]

    opening = compute_opening_balance(client_id, ps)

    account_ids = {a["id"] for a in store.accounts.values() if a["client_id"] == client_id}

    receipts = 0
    for d in store.deposits.values():
        if d["account_id"] not in account_ids:
            continue
        if basis == "CASH":
            if d["status"] != "POSTED":
                continue
            posted_at = d.get("posted_at")
            if not posted_at:
                continue
            posted_date = posted_at[:10]
            if ps.isoformat() <= posted_date <= pe.isoformat():
                receipts += d["amount_cents"]
        else:  # ACCRUAL
            if d["status"] in ("RECEIVED", "POSTED"):
                rd = d["received_date"]
                if ps <= rd <= pe:
                    receipts += d["amount_cents"]

    disb_total = 0
    for d in store.disbursements.values():
        if d["client_id"] != client_id:
            continue
        if basis == "CASH":
            if d["status"] != "RELEASED":
                continue
            ra = d.get("released_at")
            if not ra:
                continue
            ra_date = ra[:10]
            if ps.isoformat() <= ra_date <= pe.isoformat():
                disb_total += d["amount_cents"]
        else:  # ACCRUAL
            if d["status"] == "RELEASED":
                ra = d.get("released_at")
                if ra:
                    ra_date = ra[:10]
                    if ps.isoformat() <= ra_date <= pe.isoformat():
                        disb_total += d["amount_cents"]
                        continue
            if d["status"] == "APPROVED":
                srd = d["scheduled_release_date"]
                if ps <= srd <= pe:
                    disb_total += d["amount_cents"]

    ending = opening + receipts - disb_total
    return receipts, disb_total, opening, ending


# --- bond_utilization ----------------------------------------------------

def refresh_bonds():
    recompute_bond_rollups()
