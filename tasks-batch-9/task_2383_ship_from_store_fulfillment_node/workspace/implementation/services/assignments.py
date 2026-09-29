"""FulfillmentAssignment creation and release helpers."""
import clock
from constants import (
    MIN_BILLABLE_LABOR_MINUTES, PACKAGE_CLASS_TO_TYPE, PACKAGE_RANK,
    PICK_SLA_MINUTES,
)
from db import db, new_row
from services.costs import component_cost, provisional_labor_minutes
from services.derive import assignment_lines_of, open_window
from util import D, add_minutes, n2, start_of_day


def derived_package_type(line_units):
    """Largest package_class among the served SKUs, mapped to a package type."""
    best = None
    for order_line, units in line_units:
        sku = db.skus[order_line["sku_id"]]
        candidate = PACKAGE_CLASS_TO_TYPE[sku["package_class"]]
        if best is None or PACKAGE_RANK[candidate] > PACKAGE_RANK[best]:
            best = candidate
    return best or "SMALL_BOX"


def billable_weight(line_units):
    total = 0
    for order_line, units in line_units:
        total += db.skus[order_line["sku_id"]]["unit_weight_grams"] * units
    return total


def pick_deadline(store, created_at):
    """min(created_at + PICK_SLA_MINUTES, the cutoff instant on created_at's date)."""
    sla = add_minutes(created_at, PICK_SLA_MINUTES)
    cutoff = add_minutes(start_of_day(created_at), store["cutoff_utc_minutes"])
    return sla if sla <= cutoff else cutoff


def provisional_cost(order, store, line_units, assigned_units, package_type):
    labor = provisional_labor_minutes(store, assigned_units)
    return component_cost(order, store, line_units, labor, assigned_units, package_type)


def final_cost(order, store, assignment):
    line_units = []
    for al in assignment_lines_of(assignment["id"]):
        line_units.append((db.order_lines[al["order_line_id"]], al["units_picked"]))
    line_units.sort(key=lambda pair: pair[0]["_seq"])
    labor = max(D(assignment["labor_minutes_actual"] or 0),
                D(MIN_BILLABLE_LABOR_MINUTES))
    return component_cost(order, store, line_units, labor, assignment["picked_units"],
                          assignment["package_type"])


def create_assignment(order, store, run, allocation, reroute_generation):
    """allocation is a list of (order_line, units) ascending OrderLine.created_at."""
    window = open_window(store["id"])
    assigned_units = sum(units for _line, units in allocation)
    package_type = derived_package_type(allocation)
    created_at = clock.now()
    assignment = new_row("assignments", {
        "order_id": order["id"],
        "store_id": store["id"],
        "routing_run_id": run["id"],
        "carrier_pickup_id": None,
        "superseded_by_routing_run_id": None,
        "epoch": window["epoch"] if window else 0,
        "status": "ASSIGNED",
        "assigned_units": assigned_units,
        "picked_units": 0,
        "shortfall_units": 0,
        "labor_minutes_reserved": n2(provisional_labor_minutes(store, assigned_units)),
        "labor_minutes_actual": None,
        "package_type": None,
        "derived_package_type": package_type,
        "billable_weight_grams": billable_weight(allocation),
        "provisional_cost_cents": provisional_cost(order, store, allocation,
                                                   assigned_units, package_type),
        "final_cost_cents": None,
        "pick_deadline_utc": pick_deadline(store, created_at),
        "accepted_at": None,
        "picked_at": None,
        "packed_at": None,
        "shipped_at": None,
        "cycle_time_minutes": None,
        "reroute_generation": reroute_generation,
        "reject_reason_code": None,
        "cancel_reason_code": None,
    })
    for order_line, units in allocation:
        new_row("assignment_lines", {
            "assignment_id": assignment["id"],
            "order_line_id": order_line["id"],
            "units_assigned": units,
            "units_picked": 0,
            "units_cancelled": 0,
        })
    return assignment


def release_assignment(assignment, terminal_status, reason_code,
                       to_cancelled_units=False, superseded_by=None):
    """Move an assignment to REJECTED/CANCELLED and release its held units.

    The released amount is what the assignment was still contributing to the
    demand lines; with to_cancelled_units the units become the lines'
    cancelled_units, otherwise they fall back to open_units.
    """
    released_total = 0
    for al in assignment_lines_of(assignment["id"]):
        contributing = al["units_assigned"] - al["units_cancelled"]
        if terminal_status == "REJECTED":
            al["units_cancelled"] = al["units_assigned"]
        else:
            al["units_cancelled"] = al["units_assigned"] - al["units_picked"]
        released_total += contributing
        if to_cancelled_units and contributing > 0:
            line = db.order_lines[al["order_line_id"]]
            line["cancelled_units"] += contributing
    assignment["status"] = terminal_status
    if terminal_status == "REJECTED":
        assignment["reject_reason_code"] = reason_code
    else:
        assignment["cancel_reason_code"] = reason_code
    if superseded_by:
        assignment["superseded_by_routing_run_id"] = superseded_by
    return released_total
