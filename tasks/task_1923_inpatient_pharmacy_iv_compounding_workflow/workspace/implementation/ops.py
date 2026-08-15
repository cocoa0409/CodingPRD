"""Cross-entity operations: cascades, sweeps, ledger, batch recompute."""

from decimal import Decimal

import db
import calc


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

EVENT_DELTAS = {
    "RESTOCK": +1, "DISPENSE": -1, "RETURN": +1, "WASTE": -1, "ADJUSTMENT": None,
}


def append_event(pocket, event_type, units_delta, recorded_by,
                 order_id=None, witness_staff_id=None, observed_count_units=None):
    """Append an InventoryEvent and apply it to the pocket's on-hand."""
    ev = db.append_fields()
    ev.update({
        "pocket_id": pocket["id"],
        "order_id": order_id,
        "recorded_by_staff_id": recorded_by,
        "witness_staff_id": witness_staff_id,
        "event_type": event_type,
        "units_delta": units_delta,
        "observed_count_units": observed_count_units,
        "expected_on_hand_after": pocket["on_hand_units"] + units_delta,
        "occurred_at": db.now(),
    })
    db.events[ev["id"]] = ev
    pocket["on_hand_units"] += units_delta
    return ev


def replay_on_hand(pocket_id):
    """Chronological replay: occurred_at ASC, created_at (seq) ASC tie-break."""
    evs = [e for e in db.events.values() if e["pocket_id"] == pocket_id]
    evs.sort(key=lambda e: (e["occurred_at"], e["_seq"]))
    total = 0
    for e in evs:
        total += e["units_delta"]
    return total


# ---------------------------------------------------------------------------
# Waste records
# ---------------------------------------------------------------------------

def append_waste_record(recorded_by, reason, batch_id=None, volume_ml=None,
                        pocket_id=None, units=None, witness_staff_id=None):
    wr = db.append_fields()
    wr.update({
        "batch_id": batch_id,
        "pocket_id": pocket_id,
        "volume_ml": volume_ml,
        "units": units,
        "reason": reason,
        "recorded_by_staff_id": recorded_by,
        "witness_staff_id": witness_staff_id,
    })
    db.waste_records[wr["id"]] = wr
    return wr


# ---------------------------------------------------------------------------
# Batch derived figures
# ---------------------------------------------------------------------------

def recompute_batch_derived(batch):
    """Refresh demand_ml, vials_used, delivered_ml from current preparations."""
    demand, vials = calc.compute_demand_and_vials(batch)
    batch["demand_ml"] = demand
    batch["vials_used"] = vials
    batch["delivered_ml"] = calc.compute_delivered(batch["id"])


def live_preparation_count(batch_id):
    return sum(
        1 for p in calc.batch_preparations(batch_id)
        if p["status"] in ("PLANNED", "COMPOUNDED", "QA_PASSED")
    )


# ---------------------------------------------------------------------------
# Order discontinue / supersede cascade (PRD Section 3.3, levels 1-3)
# ---------------------------------------------------------------------------

def order_cancellation_cascade(order):
    """L1 preps -> CANCELLED; L2 batch recompute/auto-cancel; L3 hood cancel."""
    affected_batches = {}
    # L1: cancel this order's preparations in PLANNED or COMPOUNDED.
    for prep in db.preparations.values():
        if prep["order_id"] == order["id"] and prep["status"] in ("PLANNED", "COMPOUNDED"):
            prep["status"] = "CANCELLED"
            db.touch(prep)
            affected_batches[prep["batch_id"]] = True
    # L2: recompute affected batches; auto-cancel empty DRAFT/IN_PROGRESS ones.
    for batch_id in affected_batches:
        batch = db.batches[batch_id]
        recompute_batch_derived(batch)
        db.touch(batch)
        if (
            batch["status"] in ("DRAFT", "IN_PROGRESS")
            and live_preparation_count(batch_id) == 0
        ):
            batch["status"] = "CANCELLED"
            db.touch(batch)
            # L3: cancel the hood session of a batch cancelled at L2.
            session = db.sessions.get(batch["hood_session_id"])
            if session is not None and session["status"] in ("SCHEDULED", "IN_USE"):
                session["status"] = "CANCELLED"
                db.touch(session)


def open_order(order):
    return (
        order["verification_status"] in ("PENDING", "VERIFIED", "ON_HOLD")
        and order["fulfillment_status"] not in ("DISPENSED", "ADMINISTERED")
    )


def order_is_terminal(order):
    return (
        order["verification_status"] in ("DISCONTINUED", "SUPERSEDED")
        or order["fulfillment_status"] == "ADMINISTERED"
    )


# ---------------------------------------------------------------------------
# Substitution protocol flagging / compensation cascades (Section 3.8)
# ---------------------------------------------------------------------------

def protocol_flagging_cascade(protocol):
    """Activation: flag open orders on the shortage drug; block its pockets."""
    for order in db.orders.values():
        if (
            order["drug_product_id"] == protocol["shortage_drug_product_id"]
            and order["verification_status"] in ("PENDING", "VERIFIED", "ON_HOLD")
            and order["fulfillment_status"] not in ("DISPENSED", "ADMINISTERED")
        ):
            order["substitution_pending"] = True
            db.touch(order)
    for pocket in db.pockets.values():
        if pocket["drug_product_id"] == protocol["shortage_drug_product_id"]:
            pocket["pick_blocked"] = True
            db.touch(pocket)


def protocol_compensation_cascade(protocol):
    """Revoke/expire: unflag not-yet-substituted orders; unblock pockets."""
    for order in db.orders.values():
        if (
            order["drug_product_id"] == protocol["shortage_drug_product_id"]
            and order["substitution_pending"]
            and order["substituted_by_protocol_id"] is None
        ):
            order["substitution_pending"] = False
            db.touch(order)
    for pocket in db.pockets.values():
        if pocket["drug_product_id"] == protocol["shortage_drug_product_id"] and pocket["pick_blocked"]:
            pocket["pick_blocked"] = False
            db.touch(pocket)


# ---------------------------------------------------------------------------
# Clock sweeps (Section 2.6)
# ---------------------------------------------------------------------------

def run_expiry_sweeps(recorded_by):
    """Preparations at/past bud_expiry -> EXPIRED; ACTIVE protocols expired.

    Runs when the logical clock is set and before any dispense is processed.
    """
    now = db.now()
    preps = sorted(
        db.preparations.values(), key=lambda p: (p["created_at"], p["_seq"])
    )
    for prep in preps:
        if (
            prep["status"] in ("COMPOUNDED", "QA_PASSED")
            and prep["bud_expiry"] is not None
            and now >= prep["bud_expiry"]
        ):
            prep["status"] = "EXPIRED"
            db.touch(prep)
            batch = db.batches.get(prep["batch_id"])
            append_waste_record(
                recorded_by=recorded_by,
                reason="EXPIRED",
                batch_id=prep["batch_id"],
                volume_ml=prep["prepared_volume_ml"],
            )
            if batch is not None:
                recompute_batch_derived(batch)
                db.touch(batch)
    for protocol in sorted(
        db.protocols.values(), key=lambda p: (p["created_at"], p["_seq"])
    ):
        if protocol["status"] == "ACTIVE" and now >= protocol["expires_at"]:
            protocol["status"] = "EXPIRED"
            db.touch(protocol)
            protocol_compensation_cascade(protocol)
