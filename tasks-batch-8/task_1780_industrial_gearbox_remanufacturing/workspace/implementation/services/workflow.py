"""Workflow helpers: credit ledger, scope totals, eligibility, shared lookups."""
from datetime import datetime, timedelta, timezone

import db
from db import store, touch, set_field, parse_iso_dt, parse_iso_date
from services import pricing

ORDER_TERMINAL = ("COMPLETED", "CANCELLED")
# PRD 2.10: statuses whose approved_scope_cents count toward customer exposure.
CREDIT_SUM_STATUSES = ("APPROVED", "IN_BUILD", "ASSEMBLY", "RUN_IN",
                       "READY_TO_SHIP", "SHIPPED")


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def order_unit(order):
    return store.units.get(order["gear_unit_id"])


def order_customer(order):
    unit = order_unit(order)
    return store.customers.get(unit["customer_id"]) if unit else None


def orders_of_unit(unit_id):
    return [o for o in store.orders.values() if o["gear_unit_id"] == unit_id]


def findings_of_order(order_id):
    return [f for f in store.findings.values() if f["reman_order_id"] == order_id]


def decisions_of_order(order_id):
    return [d for d in store.decisions.values() if d["reman_order_id"] == order_id]


def assembly_records_of_order(order_id):
    return [a for a in store.assembly_records.values()
            if a["reman_order_id"] == order_id]


def run_in_tests_of_order(order_id):
    return [t for t in store.run_in_tests.values() if t["reman_order_id"] == order_id]


def shipments_of_order(order_id):
    return [s for s in store.shipments.values() if s["reman_order_id"] == order_id]


def claims_of_order(order_id):
    return [c for c in store.warranty_claims.values() if c["reman_order_id"] == order_id]


def assignments_of_order(order_id):
    return [a for a in store.loaner_assignments.values()
            if a["reman_order_id"] == order_id]


def assignments_of_loaner(loaner_id):
    return [a for a in store.loaner_assignments.values()
            if a["loaner_unit_id"] == loaner_id]


def has_nonterminal_order(unit_id, exclude_order_id=None):
    for order in orders_of_unit(unit_id):
        if order["id"] == exclude_order_id:
            continue
        if order["status"] not in ORDER_TERMINAL:
            return True
    return False


# --------------------------------------------------------------------------
# Credit ledger (PRD 2.10)
# --------------------------------------------------------------------------

def refresh_customer_credit(customer):
    """Recompute outstanding_approved_cents as the derived sum, then credit_hold.

    credit_hold is true iff outstanding is STRICTLY greater than the limit;
    landing exactly on the limit is not a hold.
    """
    total = 0
    for unit in store.units.values():
        if unit["customer_id"] != customer["id"]:
            continue
        for order in orders_of_unit(unit["id"]):
            if order["status"] in CREDIT_SUM_STATUSES:
                total += order["approved_scope_cents"]
    hold = total > customer["credit_limit_cents"]
    if (customer["outstanding_approved_cents"] != total
            or customer["credit_hold"] != hold):
        customer["outstanding_approved_cents"] = total
        customer["credit_hold"] = hold
        touch(customer)


# --------------------------------------------------------------------------
# Scope pricing (PRD 3.3)
# --------------------------------------------------------------------------

def pending_decisions(order_id):
    return [d for d in decisions_of_order(order_id)
            if d["approval_status"] == "PENDING"]


def compute_approved_scope(order_id):
    """Sum of line_total_cents over the order's currently PENDING decisions."""
    return sum(d["line_total_cents"] for d in pending_decisions(order_id))


def recompute_line_totals(order):
    """Recompute each PENDING decision's line total (per-line rounding)."""
    for d in pending_decisions(order["id"]):
        new_total = pricing.component_line_total_cents(
            d["action"], d["labor_hours"], d["material_cents"], order["rush"])
        if new_total != d["line_total_cents"]:
            d["line_total_cents"] = new_total
            touch(d)


# --------------------------------------------------------------------------
# Freight / rigging bay (PRD 3.5)
# --------------------------------------------------------------------------

def _bay_occupancy(shipment):
    """Half-open occupancy [date, date + hours + RIGGING_BUFFER_HOURS)."""
    start = datetime.combine(parse_iso_date(shipment["rigging_bay_date"]),
                             datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(hours=shipment["rigging_bay_hours"]
                            + pricing.RIGGING_BUFFER_HOURS)
    return start, end


def rigging_bay_conflicts(rigging_bay_date, rigging_bay_hours, exclude_id=None):
    new_start, new_end = _bay_occupancy({
        "rigging_bay_date": rigging_bay_date,
        "rigging_bay_hours": rigging_bay_hours,
    })
    for other in store.shipments.values():
        if other["id"] == exclude_id or other["status"] == "CANCELLED":
            continue
        o_start, o_end = _bay_occupancy(other)
        if o_start < new_end and new_start < o_end:
            return True
    return False


# --------------------------------------------------------------------------
# Loaner windows (PRD 3.6): half-open [start_date, end_date)
# --------------------------------------------------------------------------

def loaner_window_overlaps(loaner_id, start_date, end_date, exclude_id=None):
    new_start = parse_iso_date(start_date)
    new_end = parse_iso_date(end_date)
    for other in store.loaner_assignments.values():
        if other["loaner_unit_id"] != loaner_id:
            continue
        if other["id"] == exclude_id or other["status"] == "CANCELLED":
            continue
        o_start = parse_iso_date(other["start_date"])
        o_end = parse_iso_date(other["end_date"])
        if o_start < new_end and new_start < o_end:
            return True
    return False


# --------------------------------------------------------------------------
# Warranty eligibility (PRD 3.7): dual basis, hours evaluated before calendar
# --------------------------------------------------------------------------

def resolve_claim_eligibility(claim, order):
    """Copy the warranty clock basis from the COMPLETED order and compute the
    dual-basis verdict. Caller touches the claim."""
    claim["warranty_clock_start_hours"] = order["completed_at_hours"]
    hours_since = claim["reported_hours"] - order["completed_at_hours"]
    claim["hours_since_reman"] = hours_since
    verdict_hours = ("COVERED" if hours_since <= pricing.WARRANTY_HOURS_LIMIT
                     else "EXPIRED_HOURS")
    created = parse_iso_dt(claim["created_at"])
    completed = parse_iso_dt(order["completed_at_utc"])
    calendar_days = (created - completed).days  # whole days
    verdict_cal = ("COVERED" if calendar_days <= pricing.WARRANTY_CALENDAR_DAYS
                   else "EXPIRED_CALENDAR")
    if verdict_hours == "COVERED" and verdict_cal == "COVERED":
        claim["eligibility"] = "COVERED"
    elif verdict_hours != "COVERED":
        claim["eligibility"] = "EXPIRED_HOURS"
    else:
        claim["eligibility"] = "EXPIRED_CALENDAR"
