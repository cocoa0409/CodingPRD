"""Cross-entity cascades (PRD sections 3.3, 3.5, 3.6, 3.7, 3.8, 3.9)."""

import constants
import db
import util
from db import store
from services import calc


# ----------------------------------------------------------- recall supersession
def _open_recalls(patient_id, protocol):
    return [
        r
        for r in store.all_rows("recalls")
        if r["patient_id"] == patient_id
        and r["protocol"] == protocol
        and r["status"] in ("SCHEDULED_DUE", "OVERDUE")
    ]


def open_recall(patient, protocol, risk_tier, anchor_date, source_specimen_id):
    """Create a recall, superseding every open recall of the same patient and protocol."""
    predecessors = _open_recalls(patient["id"], protocol)
    interval = calc.interval_months(protocol, risk_tier)
    predecessor_recall_id = predecessors[-1]["id"] if predecessors else None
    row = db.new_row(
        "recalls",
        {
            "patient_id": patient["id"],
            "protocol": protocol,
            "risk_tier": risk_tier,
            "anchor_date": anchor_date,
            "interval_months": interval,
            "due_on": util.add_months(anchor_date, interval),
            "due_basis": "PROTOCOL_ANCHORED",
            "status": "SCHEDULED_DUE",
            "lapse_days": 0,
            "predecessor_recall_id": predecessor_recall_id,
            "source_specimen_id": source_specimen_id,
            "satisfying_case_id": None,
            "closed_reason": None,
        },
    )
    # Processed in ascending created_at order.
    for predecessor in predecessors:
        predecessor["status"] = "SUPERSEDED"
        db.touch(predecessor)
    # Counters recomputed; the patient's version increments by 1.
    db.touch_once(patient)
    return row


# ------------------------------------------------------ CASCADE A: case complete
def satisfy_recall(case):
    ptype = store.get("procedure_types", case["procedure_type_id"])
    if ptype is None:
        return None
    candidates = []
    for recall in store.all_rows("recalls"):
        if recall["patient_id"] != case["patient_id"]:
            continue
        if recall["status"] not in ("SCHEDULED_DUE", "OVERDUE"):
            continue
        if ptype["code"] not in constants.PROTOCOL_SURVEILLANCE_TYPES[recall["protocol"]]:
            continue
        candidates.append(recall)
    if not candidates:
        return None
    chosen = min(candidates, key=lambda r: (r["due_on"], r["created_at"], r["_seq"]))
    chosen["status"] = "SATISFIED"
    chosen["satisfying_case_id"] = case["id"]
    chosen["lapse_days"] = 0
    db.touch(chosen)
    patient = store.get("patients", case["patient_id"])
    if patient is not None:
        db.touch_once(patient)
    return chosen


# ------------------------------------------------------------------ scope moves
def soil_scope(case):
    scope = store.get("scopes", case["scope_asset_id"]) if case["scope_asset_id"] else None
    if scope is None or scope["status"] != "IN_USE":
        return None
    now = store.now()
    scope["status"] = "SOILED"
    scope["cycles_since_leak_test"] += 1
    scope["reprocess_due_at"] = util.add_hours(now, constants.SCOPE_REPROCESS_DUE_HOURS)
    scope["_soiled_at"] = now
    if scope["cycles_since_leak_test"] >= constants.SCOPE_LEAK_TEST_CYCLES:
        scope["leak_test_required"] = True
    db.touch(scope)
    return scope


def release_scope(case):
    """Cancellation and no-show: the scope returns straight to AVAILABLE, no cycle counted."""
    scope = store.get("scopes", case["scope_asset_id"]) if case["scope_asset_id"] else None
    if scope is None:
        return None
    if scope["status"] == "IN_USE":
        scope["status"] = "AVAILABLE"
        db.touch(scope)
        case["scope_asset_id"] = None
    return scope


# ----------------------------------------------------------------- device moves
def move_device_units(case, target_state, basis):
    if case["device_state"] != "RESERVED":
        return None
    lot = store.get("lots", case["device_lot_id"])
    quantity = case["device_quantity"]
    case["device_state"] = target_state
    if lot is None:
        return None
    lot["quantity_reserved"] -= quantity
    if target_state == "CONSUMED":
        lot["quantity_consumed"] += quantity
    elif target_state == "RELEASED":
        lot["quantity_available"] += quantity
    elif target_state == "WASTED":
        lot["quantity_wasted"] += quantity
    calc.rebill(lot, basis)
    db.touch(lot)
    return lot


# ------------------------------------------------------------- antibiotic sweep
def cancel_open_antibiotic_orders(case):
    for order in store.all_rows("antibiotic_orders"):
        if order["case_id"] == case["id"] and order["status"] == "ORDERED":
            order["status"] = "CANCELLED"
            db.touch(order)


# -------------------------------------------------------------------- room ledger
def bump_room(room):
    if room is not None:
        db.touch(room)
