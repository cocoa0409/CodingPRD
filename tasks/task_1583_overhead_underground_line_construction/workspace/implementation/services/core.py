"""Core shared services: record lifecycle and derived fields (PRD 2.4, 2.5, 2.8).

Derived fields (Crew.status, Equipment.status, BidItem.accepted_quantity /
billed_quantity, StockItem.on_hand, WorkPackage counters, Invoice.hold_reason
and DRAFT invoice lines) are recomputed on read from the ledger — they are
never stored as independent facts, so the two conservation principles hold by
construction.
"""
from db import db
from util import new_id, now_ts, dec, CLOCK, parse_datetime, parse_date


def new_record(collection, fields):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = now_ts()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Every mutation of a resource bumps its version and updated_at (PRD 2.4)."""
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def work_package_of_assignment(assignment):
    return db["work_packages"].get(assignment["work_package_id"])


def contract_of_work_package(wp):
    return db["contracts"].get(wp["contract_id"]) if wp else None


def contract_of_assignment(assignment):
    return contract_of_work_package(work_package_of_assignment(assignment))


# ---------------------------------------------------------------------------
# Crew / Equipment computed availability (PRD 3.2, crew_equipment_status_derivation)
# ---------------------------------------------------------------------------

def crew_status(crew) -> str:
    cid = crew["id"]
    has_callout = False
    has_standby = False
    for sa in db["storm_activations"].values():
        if sa["crew_id"] == cid and sa["status"] == "ACTIVE":
            if sa["kind"] == "CALLOUT":
                has_callout = True
            elif sa["kind"] == "STANDBY":
                has_standby = True
    if has_callout:
        return "CALLOUT"
    if has_standby:
        return "STANDBY"
    today = CLOCK.today()
    for a in db["assignments"].values():
        if a["crew_id"] == cid and a["status"] == "ACTIVE":
            if parse_date(a["start_date"]) <= today <= parse_date(a["end_date"]):
                return "ASSIGNED"
    return "AVAILABLE"


def equipment_status(equipment) -> str:
    eid = equipment["id"]
    today = CLOCK.today()
    for a in db["assignments"].values():
        if a["equipment_id"] == eid and a["status"] == "ACTIVE":
            if parse_date(a["start_date"]) <= today <= parse_date(a["end_date"]):
                return "IN_USE"
    return "AVAILABLE"


# ---------------------------------------------------------------------------
# BidItem ledgers (PRD 2.8, production_acceptance_accounting, billing pool)
# ---------------------------------------------------------------------------

def accepted_quantity(bid_item_id):
    """Sum of quantity_reported over ACCEPTED entries of this bid item."""
    total = dec(0)
    for e in db["production_entries"].values():
        if e["bid_item_id"] == bid_item_id and e["status"] == "ACCEPTED":
            total += dec(e["quantity_reported"])
    return total


def billed_quantity(bid_item_id):
    """Sum of (in_schedule_units + overrun_units) over lines of frozen,
    non-VOID invoices (SUBMITTED / APPROVED / PAID) for this bid item."""
    total = dec(0)
    for inv in db["invoices"].values():
        if inv["status"] not in ("SUBMITTED", "APPROVED", "PAID"):
            continue
        lines = inv.get("frozen_lines") or []
        for line in lines:
            if line["bid_item_id"] == bid_item_id:
                total += dec(line["in_schedule_units"]) + dec(line["overrun_units"])
    return total


# ---------------------------------------------------------------------------
# WorkPackage counters (source: computed)
# ---------------------------------------------------------------------------

def rework_open_count(work_package_id) -> int:
    n = 0
    for e in db["production_entries"].values():
        if e["status"] != "REWORK_REQUIRED":
            continue
        a = db["assignments"].get(e["assignment_id"])
        if a is not None and a["work_package_id"] == work_package_id:
            n += 1
    return n


def open_material_issue_count(work_package_id) -> int:
    n = 0
    for mi in db["material_issues"].values():
        if mi["work_package_id"] == work_package_id and mi["status"] == "OPEN":
            n += 1
    return n


# ---------------------------------------------------------------------------
# StockItem ledger (PRD 2.8, material_reconciliation)
# ---------------------------------------------------------------------------

def stock_on_hand(stock_item):
    """initial_on_hand + receipts - issued + returned (all MaterialIssue rows)."""
    sid = stock_item["id"]
    total = dec(stock_item["initial_on_hand"]) + dec(stock_item.get("_receipts_total", 0))
    for mi in db["material_issues"].values():
        if mi["stock_item_id"] == sid:
            total -= dec(mi["quantity_issued"])
            total += dec(mi["quantity_returned"])
    return total


# ---------------------------------------------------------------------------
# Invoice hold_reason (computed; PRD 3.5 / 3.9)
# ---------------------------------------------------------------------------

def invoice_hold_reason(invoice):
    if invoice["status"] == "DRAFT" and rework_open_count(invoice["work_package_id"]) > 0:
        return "OPEN_REWORK"
    return None


# ---------------------------------------------------------------------------
# Outage lazy IN_EFFECT evaluation (PRD 2.5 / 3.6)
# ---------------------------------------------------------------------------

def sweep_outages_in_effect():
    """APPROVED outages whose window contains the logical now move to IN_EFFECT.
    Runs whenever the clock is set and whenever outage requests are read or
    referenced by another operation."""
    now = CLOCK.now()
    for o in db["outage_requests"].values():
        if o["status"] != "APPROVED":
            continue
        ws = parse_datetime(o["window_start"])
        we = parse_datetime(o["window_end"])
        if ws <= now <= we:
            o["status"] = "IN_EFFECT"
            touch(o)


def outage_covers_date(work_package_id, work_date_str) -> bool:
    """True when an IN_EFFECT outage of this work package covers work_date
    (compared at UTC calendar-date granularity)."""
    sweep_outages_in_effect()
    wd = parse_date(work_date_str)
    for o in db["outage_requests"].values():
        if o["work_package_id"] != work_package_id or o["status"] != "IN_EFFECT":
            continue
        ws = parse_datetime(o["window_start"]).date()
        we = parse_datetime(o["window_end"]).date()
        if ws <= wd <= we:
            return True
    return False
