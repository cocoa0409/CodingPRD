"""Business logic: rollups, projection, cascades, policy economics (PRD §3)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import store

# PRD §3.4: property-management overhead allocation on booked expense.
OVERHEAD_BP = 250
# PRD §3.3/§3.4: mandatory cure day before carpet after paint.
CURE_BUFFER_DAYS = 1
# PRD §3.3: per-category standard durations used by the projection.
STANDARD_DAYS = {
    "REPAIR": 2, "PAINT": 2, "CARPET": 1, "CLEAN": 1,
    "APPLIANCE": 1, "FIXTURE": 1, "OTHER": 1,
}
# PRD §3.2: category scheduling order.
SEQUENCE_RANK = {
    "REPAIR": 1, "APPLIANCE": 2, "FIXTURE": 3, "PAINT": 4,
    "CARPET": 5, "CLEAN": 6, "OTHER": 7,
}
# PRD §3.1: APPLIANCE/FIXTURE/OTHER items are handled by REPAIR-trade vendors.
TRADE_FOR_CATEGORY = {
    "REPAIR": "REPAIR", "PAINT": "PAINT", "CARPET": "CARPET", "CLEAN": "CLEAN",
    "APPLIANCE": "REPAIR", "FIXTURE": "REPAIR", "OTHER": "REPAIR",
}

ESTIMATE_STATUSES = ("PLANNED", "SCHEDULED", "COMPLETED", "FAILED")
ACTUAL_STATUSES = ("COMPLETED", "FAILED")
OPEN_ASSIGNMENT_STATUSES = ("SCHEDULED", "ACCEPTED")
# Turns with an established projection (set at finalize; kept through READY).
PROJECTION_TURN_STATUSES = ("SCOPED", "IN_PROGRESS", "REWORK", "READY")
ACTIVE_TURN_STATUSES = ("SCOPED", "IN_PROGRESS", "REWORK")


def round_half_up_int(value):
    """Round a Decimal to a whole integer, half up (PRD §2.6)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Entity lookups
# ---------------------------------------------------------------------------

def items_of_turn(turn_id):
    return [i for i in store.scope_items.values() if i["turn_id"] == turn_id]


def assignments_of_turn(turn_id):
    item_ids = {i["id"] for i in items_of_turn(turn_id)}
    return [a for a in store.assignments.values()
            if a["scope_item_id"] in item_ids]


def commitments_of_unit(unit_id):
    return [c for c in store.commitments.values() if c["unit_id"] == unit_id]


def active_turn_of_unit(unit_id):
    """The unit's current turn with an established projection, if any."""
    for t in store.turns.values():
        if t["unit_id"] == unit_id and t["status"] in ACTIVE_TURN_STATUSES:
            return t
    return None


def property_of_turn(turn):
    unit = store.units.get(turn["unit_id"])
    if unit is None:
        return None
    return store.properties.get(unit["property_id"])


def vendor_open_count(vendor_id):
    """PRD §3.1: count of the vendor's assignments in SCHEDULED or ACCEPTED."""
    return sum(1 for a in store.assignments.values()
               if a["vendor_id"] == vendor_id
               and a["status"] in OPEN_ASSIGNMENT_STATUSES)


def vendor_public(vendor):
    """Vendor view with the open-assignment count derived from live state."""
    out = dict(vendor)
    out["open_assignment_count"] = vendor_open_count(vendor["id"])
    return out


# ---------------------------------------------------------------------------
# Turn rollups (PRD §2.7, §3.3, §3.4)
# ---------------------------------------------------------------------------

def recompute_estimate(turn):
    turn["estimated_cost_cents"] = sum(
        i["estimated_cost_cents"] for i in items_of_turn(turn["id"])
        if i["status"] in ESTIMATE_STATUSES)


def recompute_actuals(turn):
    expense = 0
    capital = 0
    booked = 0
    for i in items_of_turn(turn["id"]):
        if i["status"] not in ACTUAL_STATUSES:
            continue
        actual = i["actual_cost_cents"] or 0
        if i["classification"] == "CAPITAL":
            capital += actual
        else:
            expense += actual
            # PRD §3.4: per-item overhead rounded half up BEFORE summation.
            overhead = round_half_up_int(
                Decimal(actual) * OVERHEAD_BP / Decimal(10000))
            booked += actual + overhead
    turn["expense_actual_cents"] = expense
    turn["capital_actual_cents"] = capital
    turn["total_actual_cents"] = expense + capital
    turn["booked_expense_cents"] = booked


def compute_projection(turn):
    """PRD §3.3 projected_ready_date: anchor at max(clock date, latest active
    assignment end), then walk PLANNED items in (sequence_rank, created_at)
    order adding standard days, with a cure day before any CARPET item while
    paint work on the turn is not complete."""
    anchor = db.logical_date()
    ends = [db.parse_date(a["end_date"]) for a in assignments_of_turn(turn["id"])
            if a["status"] in OPEN_ASSIGNMENT_STATUSES]
    if ends:
        anchor = max(anchor, max(ends))
    items = items_of_turn(turn["id"])
    paint_open = any(
        i["category"] == "PAINT"
        and i["status"] not in ("COMPLETED", "VOIDED", "REJECTED", "FAILED")
        for i in items)
    planned = sorted(
        (i for i in items if i["status"] == "PLANNED"),
        key=lambda i: (i["sequence_rank"], i["created_at"], i["_seq"]))
    for i in planned:
        if i["category"] == "CARPET" and paint_open:
            anchor += timedelta(days=CURE_BUFFER_DAYS)
        anchor += timedelta(days=STANDARD_DAYS[i["category"]])
    return anchor


def evaluate_commitment_risk(turn):
    """PRD §3.8: every open commitment on the turn's unit rides the projection."""
    proj = turn.get("projected_ready_date")
    if not proj:
        return
    projected = db.parse_date(proj)
    for c in commitments_of_unit(turn["unit_id"]):
        if c["status"] not in ("ACTIVE", "AT_RISK"):
            continue
        committed = db.parse_date(c["committed_delivery_date"])
        new_status = "AT_RISK" if projected > committed else "ACTIVE"
        if new_status != c["status"]:
            c["status"] = new_status
            db.touch(c)


def sync_turn(turn, projection=True):
    """Re-derive the turn's rollups from its items/assignments and re-evaluate
    commitment risk. Refreshes updated_at but never bumps version — turn
    version advances only at the §3-marked transitions."""
    recompute_estimate(turn)
    recompute_actuals(turn)
    if projection and turn["status"] in PROJECTION_TURN_STATUSES:
        turn["projected_ready_date"] = compute_projection(turn).isoformat()
    db.refresh(turn)
    evaluate_commitment_risk(turn)


# ---------------------------------------------------------------------------
# Scope-creep tiering (PRD §3.5)
# ---------------------------------------------------------------------------

def scope_creep_tier(turn, new_estimate_cents):
    prop = property_of_turn(turn)
    budget = turn["approved_budget_cents"]
    would_be = turn["estimated_cost_cents"] + new_estimate_cents
    if budget > 0:
        variance_bp = round_half_up_int(
            Decimal((would_be - budget) * 10000) / Decimal(budget))
    else:
        variance_bp = 0 if would_be <= 0 else 10 ** 12
    if variance_bp <= prop["pm_threshold_bp"]:
        return "NONE"
    if variance_bp <= prop["rm_threshold_bp"]:
        return "PM"
    return "RM"


# ---------------------------------------------------------------------------
# Replacement economics (PRD §3.6)
# ---------------------------------------------------------------------------

def repair_economical(prop, repair_estimate, replace_estimate,
                      repair_life_years, remaining_life_years):
    """True iff a REPAIR decision clears the property's active policy variant."""
    if prop["replacement_policy"] == "PERCENT_OF_REPLACE":
        ceiling = round_half_up_int(Decimal(replace_estimate) * Decimal("0.5"))
        return repair_estimate < ceiling
    # COST_PER_YEAR: integer-exact cross-multiplied comparison.
    return (repair_estimate * remaining_life_years
            < replace_estimate * repair_life_years)


# ---------------------------------------------------------------------------
# Property benchmark (PRD §3.9)
# ---------------------------------------------------------------------------

def recompute_property_benchmark(property_id):
    prop = store.properties.get(property_id)
    if prop is None:
        return
    closed = []
    for t in store.turns.values():
        if t["status"] != "CLOSED":
            continue
        unit = store.units.get(t["unit_id"])
        if unit is not None and unit["property_id"] == property_id:
            closed.append(t)
    n = len(closed)
    prop["benchmark_turn_count"] = n
    if n == 0:
        prop["avg_booked_expense_cents"] = 0
        prop["avg_days_to_ready"] = 0
    else:
        total_booked = sum(t["booked_expense_cents"] for t in closed)
        prop["avg_booked_expense_cents"] = round_half_up_int(
            Decimal(total_booked) / Decimal(n))
        total_days = sum(
            (db.parse_date(t["actual_ready_date"])
             - db.parse_date(t["started_on"])).days for t in closed)
        prop["avg_days_to_ready"] = round_half_up_int(
            Decimal(total_days) / Decimal(n))
    db.touch(prop)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cancel_item_assignments(item):
    """Voiding an item cancels its SCHEDULED|ACCEPTED assignments (PRD §3.5)."""
    for a in store.assignments.values():
        if (a["scope_item_id"] == item["id"]
                and a["status"] in OPEN_ASSIGNMENT_STATUSES):
            a["status"] = "CANCELLED"
            db.touch(a)
