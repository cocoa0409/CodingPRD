"""Certification effectiveness, style compliance posture and recycled content."""

from decimal import Decimal

import calc
from calc import dec, rhu
from db import ordered, store, touch
from services import ledgers

RECYCLED_RUN_STATUSES = ("GREIGE", "BACKED", "RELEASED")


# ---- certificate effectiveness -------------------------------------------

def certifications_of_style(style_id):
    return ordered([c for c in store.certifications.values() if c["style_id"] == style_id])


def effective_cert(style_id, cert_type):
    """ACTIVE and expires strictly later than the logical clock (PRD 3.8)."""
    for cert in certifications_of_style(style_id):
        if cert["cert_type"] != cert_type or cert["status"] != "ACTIVE":
            continue
        if cert["_expires_dt"] > store.clock_dt:
            return cert
    return None


def has_effective_flammability_cert(style_id):
    return effective_cert(style_id, "DOC_FF_1_70") is not None


# ---- style compliance cascades -------------------------------------------

def suspend_style_if_uncertified(style):
    """ACTIVE -> SUSPENDED when the last effective DOC_FF_1_70 disappears."""
    if style["status"] != "ACTIVE":
        return None
    if has_effective_flammability_cert(style["id"]):
        return None
    style["status"] = "SUSPENDED"
    touch(style)
    held = []
    for run in ledgers.runs_of_style(style["id"]):
        if run["status"] == "SCHEDULED":
            run["status"] = "HELD"
            touch(run)
            held.append(run["id"])
    return held


def reactivate_style_if_certified(style):
    """SUSPENDED -> ACTIVE when a fresh effective DOC_FF_1_70 exists."""
    if style["status"] != "SUSPENDED":
        return None
    if not has_effective_flammability_cert(style["id"]):
        return None
    style["status"] = "ACTIVE"
    touch(style)
    for run in ledgers.runs_of_style(style["id"]):
        if run["status"] == "HELD":
            run["status"] = "SCHEDULED"
            touch(run)
    return True


def evaluate_runout_discontinuation():
    """RUNOUT -> DISCONTINUED, evaluated after every cut-order ship or cancel."""
    for style in ordered(list(store.styles.values())):
        if style["status"] != "RUNOUT":
            continue
        live_stock = False
        for run in ledgers.runs_of_style(style["id"]):
            for roll in ledgers.rolls_of_run(run["id"]):
                if roll["inventory_status"] in ("AVAILABLE", "COMMITTED"):
                    live_stock = True
                    break
            if live_stock:
                break
        if live_stock:
            continue
        open_order = False
        for order in ledgers.orders_of_style(style["id"]):
            if order["status"] in ("SUBMITTED", "ALLOCATED", "BACKORDERED", "CUT"):
                open_order = True
                break
        if open_order:
            continue
        style["status"] = "DISCONTINUED"
        touch(style)


# ---- calculation 10: recycled content (two accounting bases) --------------

def recycled_content(style_id):
    batch_ids = []
    for run in ledgers.runs_of_style(style_id):
        if run["status"] not in RECYCLED_RUN_STATUSES:
            continue
        batch_id = run.get("fiber_batch_id")
        if batch_id and batch_id not in batch_ids:
            batch_ids.append(batch_id)

    contributions = []
    for batch_id in batch_ids:
        batch = store.fiber_batches.get(batch_id)
        if not batch:
            continue
        primary = store.polymer_lots.get(batch["polymer_lot_id"])
        if primary:
            contributions.append((primary, dec(batch["input_kg"])))
        if batch.get("blend_polymer_lot_id"):
            blend = store.polymer_lots.get(batch["blend_polymer_lot_id"])
            if blend:
                contributions.append((blend, dec(batch.get("blend_input_kg") or 0)))

    total = Decimal(0)
    mass_balance = Decimal(0)
    physical = Decimal(0)
    for lot, kg in contributions:
        total += kg
        mass_balance += kg * dec(lot["recycled_content_pct"]) / Decimal(100)
        if lot["segregated"] and dec(lot["recycled_content_pct"]) == Decimal("100.00"):
            physical += kg

    def pct(recycled):
        if total == 0:
            return float(Decimal("0.00"))
        return float(rhu(recycled * Decimal(100) / total, 2))

    return {
        "mass_balance_pct": pct(mass_balance),
        "physical_segregation_pct": pct(physical),
        "qualifying_kg": float(rhu(total, 3)),
        "qualifying_fiber_batch_ids": batch_ids,
    }


def recycled_pct_for_basis(style_id, accounting_basis):
    report = recycled_content(style_id)
    if accounting_basis == "PHYSICAL_SEGREGATION":
        return report["physical_segregation_pct"]
    return report["mass_balance_pct"]


def nsf_140_eligible(pct):
    return dec(pct) >= calc.NSF_140_MIN_RECYCLED_PCT
