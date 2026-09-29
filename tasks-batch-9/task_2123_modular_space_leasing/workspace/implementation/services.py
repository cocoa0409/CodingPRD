"""Shared business helpers: derived counters, exposure, occupancy calendar."""
from datetime import timedelta

import calc
import db
from db import store, touch, ordered


# ---------------------------------------------------------------- lookups

def units_of_branch(branch_id):
    return [u for u in store.units.values() if u["current_branch_id"] == branch_id]


def leases_of_customer(customer_id):
    return ordered([l for l in store.leases.values() if l["customer_id"] == customer_id])


def leases_of_unit(unit_id):
    return ordered([l for l in store.leases.values() if l["unit_id"] == unit_id])


def jobs_of_lease(lease_id):
    return ordered([j for j in store.jobs.values() if j["lease_id"] == lease_id])


def packages_of_lease(lease_id):
    return ordered([p for p in store.accessory_packages.values() if p["lease_id"] == lease_id])


def permits_of_lease(lease_id):
    return ordered([p for p in store.permits.values() if p["lease_id"] == lease_id])


def assessments_of_lease(lease_id):
    return ordered([a for a in store.assessments.values() if a["lease_id"] == lease_id])


def line_items_of_assessment(assessment_id):
    return ordered([li for li in store.line_items.values()
                    if li["damage_assessment_id"] == assessment_id])


def refurb_orders_of_unit(unit_id):
    return ordered([o for o in store.refurb_orders.values() if o["unit_id"] == unit_id])


def spec_of_unit(unit):
    return store.building_specs.get(unit["building_spec_id"])


# ---------------------------------------------------------------- recomputes

def recompute_branch(branch):
    """Branch counters are always recomputed from scratch (PRD 2.10)."""
    if branch is None:
        return
    in_yard, available, utilization = calc.branch_counters(units_of_branch(branch["id"]))
    branch["units_in_yard"] = in_yard
    branch["units_available"] = available
    branch["utilization_pct"] = utilization
    touch(branch)


def recompute_branch_of_unit(unit):
    recompute_branch(store.branches.get(unit["current_branch_id"]))


def recompute_customer(customer, demote_on_hold_flip=False):
    """Customer exposure + credit hold (PRD 2.11)."""
    was_on_hold = customer["credit_hold"]
    balance = calc.customer_balance(leases_of_customer(customer["id"]))
    customer["outstanding_balance_cents"] = balance
    customer["credit_hold"] = balance > customer["credit_limit_cents"]
    if demote_on_hold_flip and (not was_on_hold) and customer["credit_hold"]:
        customer["credit_tier"] = "WATCH"
    touch(customer)


# ---------------------------------------------------------------- calendar

def occupied_interval(lease):
    """Closed interval a lease occupies on its unit."""
    start = calc.parse_iso_date(lease["start_date"])
    if lease["occupancy_status"] == "VACATED" and lease["actual_vacated_date"]:
        end = calc.parse_iso_date(lease["actual_vacated_date"])
    else:
        end = calc.parse_iso_date(lease["end_date"])
    return start, end


def occupancy_conflict(unit_id, start, end, extends_lease_id=None, ignore_lease_id=None):
    """Rank 20: the unit occupancy calendar with its 14-day refurbishment buffer."""
    buffer_days = timedelta(days=calc.REFURB_BUFFER_DAYS)
    for other in leases_of_unit(unit_id):
        if other["occupancy_status"] == "CANCELLED":
            continue
        if ignore_lease_id is not None and other["id"] == ignore_lease_id:
            continue
        other_start, other_end = occupied_interval(other)
        if other_start is None or other_end is None:
            continue
        exempt = (
            extends_lease_id is not None
            and other["id"] == extends_lease_id
            and start == other_end + timedelta(days=1)
        )
        pad = timedelta(days=0) if exempt else buffer_days
        if start <= other_end + pad and end >= other_start - pad:
            return True
    return False


# ---------------------------------------------------------------- filters

def apply_filters(records, filters):
    """Exact-match query filters; a filter absent from the query is ignored."""
    from flask import request

    out = records
    for param, field in filters.items():
        value = request.args.get(param)
        if value is None or value == "":
            continue
        out = [r for r in out if str(r.get(field)) == value]
    return out
