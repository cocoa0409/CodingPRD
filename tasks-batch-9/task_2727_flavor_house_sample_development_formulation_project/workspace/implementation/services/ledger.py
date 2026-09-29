"""Mass ledger, cabinet occupancy, rig windows, panel score, lot numbers."""

import math
from datetime import timedelta
from decimal import Decimal

import constants as K
from db import db, by_creation, now_logical, rhu, touch
from services import graph

SHIPMENT_ALLOCATING = ("DRAFT", "PACKET_ASSEMBLED", "BLOCKED", "DISPATCHED")


# --- sample mass ledger (§1.3 sample_mass_ledger) ---------------------------

def allocated_g(lot_id):
    total = 0
    for row in db.retentions.values():
        if row["sample_lot_id"] == lot_id and row["status"] == "STORED":
            total += row["quantity_g"]
    for row in db.tests.values():
        if row["sample_lot_id"] == lot_id:
            total += row["consumed_g"]
    for row in db.shipments.values():
        if row["sample_lot_id"] == lot_id and row["status"] in SHIPMENT_ALLOCATING:
            total += row["shipped_g"]
    return total


def available_g(lot):
    return lot["batch_size_g"] - allocated_g(lot["id"])


def reconcile_lot(lot):
    """RELEASED <-> CONSUMED follows the ledger; other dispositions are inert."""
    remaining = available_g(lot)
    if lot["disposition_status"] == "RELEASED" and remaining <= 0:
        lot["disposition_status"] = "CONSUMED"
        touch(lot)
    elif lot["disposition_status"] == "CONSUMED" and remaining > 0:
        lot["disposition_status"] = "RELEASED"
        touch(lot)


# --- lot number minting -----------------------------------------------------

def mint_lot_number(formula, brief):
    earlier = [l for l in db.lots.values() if l["formula_id"] == formula["id"]]
    sequence = len(earlier) + 1
    return "%s-I%02d-L%03d" % (brief["brief_code"], formula["iteration_no"],
                               sequence)


# --- retention slot occupancy (§1.3 retention_slot_occupancy) ---------------

def slot_count_for(quantity_g):
    return int(math.ceil(float(quantity_g) / float(K.RETENTION_SLOT_CAPACITY_G)))


def _overlaps(a_from, a_until, b_from, b_until):
    return a_from < b_until and b_from < a_until


def occupied_slots(cabinet_id, candidate_from, candidate_until):
    total = 0
    for row in db.retentions.values():
        if row["cabinet_id"] != cabinet_id or row["status"] != "STORED":
            continue
        if _overlaps(candidate_from, candidate_until,
                     row["stored_from"], row["stored_until"]):
            total += row["slot_count"]
    return total


def slots_available(cabinet):
    clock = now_logical()
    used = 0
    for row in db.retentions.values():
        if row["cabinet_id"] != cabinet["id"] or row["status"] != "STORED":
            continue
        if row["stored_from"] <= clock < row["stored_until"]:
            used += row["slot_count"]
    return cabinet["capacity_slots"] - used


def retention_period_ok(stored_from, stored_until):
    return (stored_until - stored_from) >= timedelta(days=K.RETENTION_MIN_PERIOD_DAYS)


# --- rig occupation (§1.3 rig_occupation_conflict) --------------------------

def rig_conflict(rig, candidate_start, candidate_end, exclude_test_id=None):
    buffer_delta = timedelta(minutes=rig["cleanout_buffer_minutes"])
    for row in by_creation(list(db.tests.values())):
        if row["rig_id"] != rig["id"]:
            continue
        if exclude_test_id is not None and row["id"] == exclude_test_id:
            continue
        if row["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if (candidate_start <= row["window_end"] + buffer_delta
                and row["window_start"] - buffer_delta <= candidate_end):
            return True
    return False


# --- panel score (§1.3 application_panel_score) -----------------------------

def panel_score(aroma, taste, stability):
    raw = (K.AROMA_WEIGHT * aroma + K.TASTE_WEIGHT * taste
           + K.STABILITY_WEIGHT * stability)
    return rhu(raw, 2)


def panel_verdict(score):
    return "PASSED" if score >= K.PANEL_PASS_THRESHOLD else "FAILED"


# --- yield variance (§3.9) --------------------------------------------------

def yield_variance_pct(measured_yield_kg, target_kg):
    return rhu((Decimal(measured_yield_kg) - Decimal(target_kg))
               * Decimal(100) / Decimal(target_kg), 2)


# --- lot lookups ------------------------------------------------------------

def lots_of_formula(formula_id):
    return by_creation([l for l in db.lots.values()
                        if l["formula_id"] == formula_id])


def shipments_of_lot(lot_id):
    return by_creation([s for s in db.shipments.values()
                        if s["sample_lot_id"] == lot_id])


def batches_of_formula(formula_id):
    return by_creation([b for b in db.batches.values()
                        if b["formula_id"] == formula_id])


def forecasts_of_brief(brief_id):
    return by_creation([f for f in db.forecasts.values()
                        if f["brief_id"] == brief_id])


def formulas_of_brief(brief_id):
    return by_creation([f for f in db.formulas.values()
                        if f["brief_id"] == brief_id])


def shipments_of_brief(brief_id):
    return by_creation([s for s in db.shipments.values()
                        if s["brief_id"] == brief_id])


def documents_of_shipment(shipment_id):
    rows = [d for d in db.documents.values() if d["shipment_id"] == shipment_id]
    return sorted(rows, key=lambda d: K.DOC_TYPES.index(d["doc_type"]))
