"""Domain services: common fields, numeric helpers, clock-driven locks,
allocation waterfall, and the seed-lot failure cascade."""
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db
from response import now_iso

CENTS = Decimal("1")
KG3 = Decimal("0.001")
RATE4 = Decimal("0.0001")


def new_id():
    return str(uuid.uuid4())


def new_resource(fields):
    """Common fields per PRD 2.4: id, created_at, updated_at, version."""
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(db.seq),
    }
    rec.update(fields)
    return rec


def new_log(fields):
    """SanitationLog: immutable append-only; only id + created_at (PRD 2.4)."""
    rec = {"id": new_id(), "created_at": now_iso(), "_seq": next(db.seq)}
    rec.update(fields)
    return rec


def touch(rec):
    """Refresh updated_at and bump version on every mutation (incl. cascades)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


def q3(value):
    """Kilograms carried to three decimal places."""
    return float(Decimal(value).quantize(KG3, rounding=ROUND_HALF_UP))


def line_extension_cents(qty_kg, unit_price_cents_per_kg):
    """round_half_up(qty_kg * unit_price) to whole cents; per-line first."""
    cents = (Decimal(qty_kg) * Decimal(unit_price_cents_per_kg)).quantize(
        CENTS, rounding=ROUND_HALF_UP
    )
    return int(cents)


def food_safety_satisfied():
    """Sow gate (PRD 2.6 / 3.3): an APPROVED plan must exist and no plan may
    be SUSPENDED ('while any plan is suspended the gate is no longer satisfied')."""
    plans = list(db.food_safety_plans.values())
    return any(p["status"] == "APPROVED" for p in plans) and not any(
        p["status"] == "SUSPENDED" for p in plans
    )


def recompute_subtotal(order):
    """weekly_subtotal_cents = sum of line_extension_cents over all current lines."""
    total = sum(
        li["line_extension_cents"]
        for li in db.order_items.values()
        if li["standing_order_id"] == order["id"]
    )
    order["weekly_subtotal_cents"] = total


def sync_order_locks():
    """Clock-driven weekly cycle (PRD 2.5 / 3.5): CONFIRMED -> LOCKED once the
    logical clock's weekday passes change_cutoff_day; LOCKED -> CONFIRMED on the
    weekly rollover (weekday back at/below the cutoff)."""
    wd = db.clock.weekday()  # 0=Mon..6=Sun
    for so in db.standing_orders.values():
        if so["status"] in ("CONFIRMED", "LOCKED"):
            desired = "LOCKED" if wd > so["change_cutoff_day"] else "CONFIRMED"
            if desired != so["status"]:
                so["status"] = desired
                touch(so)


def _allocation_key(line):
    """effective_week_start ASC, then StandingOrder.created_at ASC (never id)."""
    so = db.standing_orders.get(line["standing_order_id"])
    if so is None:
        return ("", "", 0, line["_seq"])
    return (
        so["effective_week_start"],
        so["created_at"],
        so["_seq"],
        line["_seq"],
    )


def run_allocation(variety_id, supply_kg):
    """Harvest allocation waterfall (PRD 3.4): offer supply to PLANNED lines for
    the variety, earliest effective week first. Full cover -> ALLOCATED; when
    supply runs out mid-line, that line is partially allocated and its unfilled
    remainder is marked SHORTED (the line itself flips to SHORTED — no split
    line is created); lines with no supply left -> SHORTED."""
    lines = [
        li
        for li in db.order_items.values()
        if li["variety_id"] == variety_id and li["fulfillment"] == "PLANNED"
    ]
    lines.sort(key=_allocation_key)
    supply = Decimal(str(supply_kg))
    if supply < 0:
        supply = Decimal("0")
    affected_orders = set()
    for li in lines:
        affected_orders.add(li["standing_order_id"])
        qty = Decimal(str(li["qty_kg"]))
        if supply <= 0:
            li["fulfillment"] = "SHORTED"
            touch(li)
            continue
        if supply >= qty:
            li["fulfillment"] = "ALLOCATED"
            touch(li)
            supply -= qty
        else:
            # Supply runs out mid-line: the line is partially allocated and its
            # unfilled remainder is marked SHORTED (PRD 3.4). The line's qty_kg
            # and line_extension_cents are creation-time figures and are not
            # mutated by allocation; the remaining supply is consumed.
            li["fulfillment"] = "SHORTED"
            touch(li)
            supply = Decimal("0")
    for oid in affected_orders:
        so = db.standing_orders.get(oid)
        if so is not None:
            recompute_subtotal(so)


def cascade_block_lot(lot_id):
    """tray_batch_failure_cascade (PRD 3.2): fail live batches of the blocked lot,
    then re-run the allocation waterfall per affected variety with the surviving
    harvest net of already-committed allocations."""
    affected_varieties = set()
    for batch in db.tray_batches.values():
        if batch["seed_lot_id"] == lot_id and batch["status"] in (
            "SOWN",
            "GERMINATING",
            "GROWING",
        ):
            batch["status"] = "FAILED"
            touch(batch)
            plan = db.crop_plans.get(batch["crop_plan_id"])
            if plan is not None:
                affected_varieties.add(plan["variety_id"])
    for variety_id in affected_varieties:
        surviving = Decimal("0")
        for batch in db.tray_batches.values():
            plan = db.crop_plans.get(batch["crop_plan_id"])
            if (
                plan is not None
                and plan["variety_id"] == variety_id
                and batch["status"] != "FAILED"
            ):
                surviving += Decimal(str(batch["harvested_kg"]))
        committed = Decimal("0")
        for li in db.order_items.values():
            if li["variety_id"] == variety_id and li["fulfillment"] in (
                "ALLOCATED",
                "DELIVERED",
                "CREDITED",
            ):
                committed += Decimal(str(li["qty_kg"]))
        supply = surviving - committed
        if supply < 0:
            supply = Decimal("0")
        run_allocation(variety_id, supply)


def expected_harvest_date(sown_dt, days_to_harvest):
    """date(sown_at) + days_to_harvest, day granularity (PRD 3.3)."""
    return (sown_dt.date() + timedelta(days=days_to_harvest)).isoformat()
