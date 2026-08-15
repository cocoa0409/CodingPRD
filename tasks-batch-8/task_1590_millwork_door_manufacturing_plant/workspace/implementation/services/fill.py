"""Truck fill efficiency (PRD §3.7, scaffold trip_fill_efficiency).

PROJECTED variant (forward-looking): includes STAGED-and-UNSCHEDULED project
openings as prospective load; recomputed on assign/unassign and on each read.
REALIZED variant (settled): committed leaves only, frozen at DEPARTED.
"""

from decimal import Decimal, ROUND_HALF_UP

import db


def _pct_1dp(numerator, denominator):
    raw = (Decimal(numerator) / Decimal(denominator)) * Decimal(100)
    return float(raw.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def compute_projected_fill(trip):
    committed = trip["leaves_committed"]
    prospective = sum(
        o["leaf_count"] for o in db.openings.values()
        if _is_project_opening(trip, o)
        and o["fab_status"] == "STAGED"
        and o["ship_status"] == "UNSCHEDULED"
    )
    return _pct_1dp(committed + prospective, trip["truck_capacity_leaves"])


def compute_realized_fill(trip):
    return _pct_1dp(trip["leaves_committed"], trip["truck_capacity_leaves"])


def _is_project_opening(trip, opening):
    order = db.orders.get(opening["order_id"])
    return order is not None and order["project_id"] == trip["project_id"]
