"""Shared business-logic services: floor-plan recompute, parts reserved_qty,
work-order charge recompute, and serialization of entities to public JSON.
"""
import calc
from clock import clock
from db import db, touch


# --- Floor-plan recompute -----------------------------------------------------
def days_outstanding_for(note):
    """Whole days between activated_on and current clock, inclusive of start,
    exclusive of end — floor of elapsed days (PRD §3.2)."""
    if note.get("activated_on") is None:
        return 0
    elapsed = clock.now() - note["activated_on"]
    days = int(elapsed.total_seconds() // 86400)
    return max(0, days)


def recompute_note(note):
    """Recompute days_outstanding, interest_accrued_cents, curtailment_stage and
    drive the ACTIVE <-> CURTAILMENT_DUE transition for an ACTIVE/CURTAILMENT_DUE
    note. Returns True if the note's status changed (so caller can bump version).

    Mutates the note in place. Does NOT bump version itself (read-time recompute
    must not bump version); the clock-advance / recompute endpoint decides.
    """
    if note["status"] not in ("ACTIVE", "CURTAILMENT_DUE"):
        return False

    days = days_outstanding_for(note)
    note["days_outstanding"] = days
    note["interest_accrued_cents"] = calc.floor_plan_interest(
        note["principal_cents"],
        note["curtailment_paid_cents"],
        note["annual_rate_bps"],
        days,
    )
    new_stage = calc.curtailment_stage(days)
    note["curtailment_stage"] = new_stage

    shortfall = calc.curtailment_shortfall(
        note["principal_cents"], new_stage, note["curtailment_paid_cents"]
    )
    changed = False
    if note["status"] == "ACTIVE" and shortfall > 0:
        note["status"] = "CURTAILMENT_DUE"
        changed = True
    return changed


def recompute_all_active_notes():
    """Called when the logical clock advances (PRD §2.9)."""
    for note in db.floor_plan_notes.values():
        if note["status"] in ("ACTIVE", "CURTAILMENT_DUE"):
            changed = recompute_note(note)
            touch(note)
            # touch bumps version + updated_at on every recompute that mutates


# --- Parts reserved_qty -------------------------------------------------------
RESERVING_WO_STATES = ("OPEN", "IN_PROGRESS", "AWAITING_PARTS")


def reserved_qty_for(part_id):
    total = 0
    for line in db.part_lines.values():
        if line["part_id"] != part_id:
            continue
        wo = db.work_orders.get(line["work_order_id"])
        if wo is not None and wo["status"] in RESERVING_WO_STATES:
            total += line["quantity"]
    return total


def available_qty_for(part):
    return part["on_hand_qty"] - reserved_qty_for(part["id"])


# --- Work order charge recompute ----------------------------------------------
def recompute_wo_parts_charge(wo):
    total = 0
    for line in db.part_lines.values():
        if line["work_order_id"] == wo["id"]:
            total += line["extended_cents"]
    wo["parts_charge_cents"] = total
    wo["total_charge_cents"] = wo["labor_charge_cents"] + wo["parts_charge_cents"]


# --- Serialization to public JSON ---------------------------------------------
def _strip(entity):
    out = {k: v for k, v in entity.items() if not k.startswith("_")}
    return out


def serialize_unit(u):
    out = _strip(u)
    # floor_planned is computed: true exactly while an ACTIVE note references it.
    # We maintain it eagerly on transitions, so just emit the stored value.
    return out


def serialize_note(note, recompute=False):
    """Serialize a floor-plan note. When recompute=True (single GET), refresh
    interest_accrued_cents and days_outstanding to the current clock first."""
    if recompute and note["status"] in ("ACTIVE", "CURTAILMENT_DUE"):
        days = days_outstanding_for(note)
        note["days_outstanding"] = days
        note["interest_accrued_cents"] = calc.floor_plan_interest(
            note["principal_cents"],
            note["curtailment_paid_cents"],
            note["annual_rate_bps"],
            days,
        )
        note["curtailment_stage"] = calc.curtailment_stage(days)
    out = _strip(note)
    if out.get("activated_on") is not None:
        from clock import format_iso8601_ms
        out["activated_on"] = format_iso8601_ms(note["activated_on"])
    return out


def serialize_part(p, recompute=False):
    out = _strip(p)
    out["reserved_qty"] = reserved_qty_for(p["id"]) if recompute else p.get("reserved_qty", 0)
    return out


def serialize_generic(e):
    out = _strip(e)
    # serialize any datetime fields stored as datetime objects
    from datetime import datetime
    from clock import format_iso8601_ms
    for k, v in list(out.items()):
        if isinstance(v, datetime):
            out[k] = format_iso8601_ms(v)
    return out


def serialize_bid(b):
    # Bid is append-only: only id + created_at (no updated_at, no version).
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "lot_id": b["lot_id"],
        "bidder_customer_id": b["bidder_customer_id"],
        "amount_cents": b["amount_cents"],
    }
