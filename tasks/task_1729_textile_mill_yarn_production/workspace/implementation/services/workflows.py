"""Cascade helpers and cross-entity workflow logic.

Centralizes mutations that touch multiple entities so routes stay thin and
every cascade bumps `updated_at` and `version` on each affected resource
(per PRD §2.6).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from db import db, now_iso
from validators import round2

from services.calculations import allocated_total


def touch(record):
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 0) + 1


def parse_instant(value):
    """Parse an ISO-8601 datetime string into an aware datetime."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    else:
        raise ValueError("not a datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Fiber lot helpers
# ---------------------------------------------------------------------------

def maybe_exhaust_fiber_lot(lot):
    """Auto-transition BLENDED -> EXHAUSTED when available weight reaches 0."""
    if lot["available_weight_lbs"] == 0 and lot["status"] == "BLENDED":
        lot["status"] = "EXHAUSTED"
        touch(lot)


def components_of_recipe(recipe_id):
    return [c for c in db.blend_components.values() if c["recipe_id"] == recipe_id]


def components_of_fiber_lot(fiber_lot_id):
    return [c for c in db.blend_components.values() if c["fiber_lot_id"] == fiber_lot_id]


def recompute_recipe_totals(recipe):
    """Recompute total_component_weight_lbs and every component's proportion_pct."""
    comps = components_of_recipe(recipe["id"])
    total = Decimal("0")
    for c in comps:
        total += c["component_weight_lbs"]
    recipe["total_component_weight_lbs"] = round2(total)
    for c in comps:
        if total > 0:
            c["proportion_pct"] = round2(c["component_weight_lbs"] / total * Decimal("100"))
        else:
            c["proportion_pct"] = Decimal("0")


# ---------------------------------------------------------------------------
# Yarn lot / dye lot helpers
# ---------------------------------------------------------------------------

def dye_lots_of_yarn_lot(yarn_lot_id):
    return [d for d in db.dye_lots.values() if d["yarn_lot_id"] == yarn_lot_id]


def quality_tests_of_dye_lot(dye_lot_id):
    tests = [t for t in db.quality_tests.values() if t["dye_lot_id"] == dye_lot_id]
    return sorted(tests, key=lambda t: (t["created_at"], t["id"]))


def latest_quality_test(dye_lot_id):
    tests = quality_tests_of_dye_lot(dye_lot_id)
    return tests[-1] if tests else None


def latest_grade(dye_lot_id):
    t = latest_quality_test(dye_lot_id)
    return t["grade"] if t else None


def rolls_of_dye_lot(dye_lot_id):
    return [r for r in db.finished_rolls.values() if r["dye_lot_id"] == dye_lot_id]


def rolls_of_order(order_id):
    return [r for r in db.finished_rolls.values() if r.get("allocated_order_id") == order_id]


# ---------------------------------------------------------------------------
# Customer order status derivation
# ---------------------------------------------------------------------------

def recompute_order_status(order):
    """Derive order status from allocated_yards vs fill threshold.

    Per PRD §3.7:
      allocated_yards > 0              -> at least PARTIALLY_ALLOCATED
      allocated_yards >= requested * (1 - tolerance/100) -> FULLY_ALLOCATED
      all allocated rolls SHIPPED      -> SHIPPED (handled by ship flow)
    """
    if order["status"] in ("SHIPPED", "CANCELLED"):
        return
    allocated = order["allocated_yards"]
    threshold = order["requested_yards"] * (Decimal(1) - order["yardage_tolerance_pct"] / Decimal(100))
    if allocated >= threshold and allocated > 0:
        order["status"] = "FULLY_ALLOCATED"
    elif allocated > 0:
        order["status"] = "PARTIALLY_ALLOCATED"
    else:
        order["status"] = "OPEN"


def recompute_order_allocated_yards(order):
    rolls = rolls_of_order(order["id"])
    live = [r for r in rolls if r["status"] in ("ALLOCATED", "SHIPPED")]
    order["allocated_yards"] = allocated_total(live)


def maybe_settle_yarn_lot_allocated(yarn_lot):
    """Auto-transition FINISHED -> ALLOCATED when every finished roll of every
    dye lot of this yarn lot is in {ALLOCATED, SHIPPED, CLOSE_OUT}."""
    if yarn_lot["status"] != "FINISHED":
        return
    dye_lots = dye_lots_of_yarn_lot(yarn_lot["id"])
    all_rolls = []
    for d in dye_lots:
        all_rolls.extend(rolls_of_dye_lot(d["id"]))
    if not all_rolls:
        return
    if all(r["status"] in ("ALLOCATED", "SHIPPED", "CLOSE_OUT") for r in all_rolls):
        yarn_lot["status"] = "ALLOCATED"
        touch(yarn_lot)


def maybe_settle_order_shipped(order):
    """FULLY_ALLOCATED -> SHIPPED when every allocated roll has shipped."""
    if order["status"] != "FULLY_ALLOCATED":
        return
    rolls = [r for r in rolls_of_order(order["id"]) if r["status"] in ("ALLOCATED", "SHIPPED")]
    if rolls and all(r["status"] == "SHIPPED" for r in rolls):
        order["status"] = "SHIPPED"
        touch(order)


# ---------------------------------------------------------------------------
# Temporal guards (PRD §2.9)
# ---------------------------------------------------------------------------

VAT_COOLDOWN = timedelta(minutes=30)


def machine_window_conflict(machine_id, window_start, window_end, exclude_assignment_id=None):
    """Half-open [start, end) overlap against SCHEDULED/IN_PROGRESS assignments on the machine."""
    for a in db.machine_assignments.values():
        if a["machine_id"] != machine_id:
            continue
        if exclude_assignment_id and a["id"] == exclude_assignment_id:
            continue
        if a["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        a_start = parse_instant(a["window_start"])
        a_end = parse_instant(a["window_end"])
        if window_start < a_end and window_end > a_start:
            return True
    return False


def vat_buffer_conflict(vat_id, scheduled_at, exclude_dye_lot_id=None):
    """Two dye lots on the same vat_id must respect a 30-minute cooldown between batches."""
    for d in db.dye_lots.values():
        if d["vat_id"] != vat_id:
            continue
        if exclude_dye_lot_id and d["id"] == exclude_dye_lot_id:
            continue
        other_at = parse_instant(d["scheduled_at"])
        if abs(scheduled_at - other_at) < VAT_COOLDOWN:
            return True
    return False
