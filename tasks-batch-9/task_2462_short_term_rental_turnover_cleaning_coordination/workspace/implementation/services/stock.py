"""The append-only stock ledger and its on-hand projection (PRD 2.9, 3.6)."""

from db import base_fields, db, ordered, touch
from services.money import cents, dec

WASTE_FACTOR = dec("1.075")


def line_movements(supply_line_id):
    return [m for m in ordered(db.stock_movements.values())
            if m["supply_line_id"] == supply_line_id]


def next_sequence_no(supply_line_id):
    return len(line_movements(supply_line_id)) + 1


def append_movement(line, reason, delta_qty, charge_cents=0, turnover_id=None,
                    checklist_task_id=None, note=None):
    movement = base_fields(versioned=False)
    movement.update({
        "supply_line_id": line["id"],
        "turnover_id": turnover_id,
        "checklist_task_id": checklist_task_id,
        "sequence_no": next_sequence_no(line["id"]),
        "reason": reason,
        "delta_qty": delta_qty,
        "unit_cost_cents_at_time": line["unit_cost_cents"],
        "charge_cents": charge_cents,
        "note": note,
    })
    db.stock_movements[movement["id"]] = movement
    return movement


def project_line(line):
    """on_hand_qty is a pure projection of the ledger; below_par follows it."""
    line["on_hand_qty"] = sum(m["delta_qty"] for m in line_movements(line["id"]))
    line["below_par"] = line["on_hand_qty"] <= line["reorder_point"]


def entry_charge_cents(line, qty_used):
    """Per-line owner chargeback: rounded half up BEFORE summation."""
    return cents(dec(line["unit_cost_cents"]) * dec(qty_used) * WASTE_FACTOR)


def book_restock_use(task, turnover, entries):
    """One RESTOCK_USE movement per submitted entry, in the order supplied."""
    total_charge = 0
    for entry in entries:
        line = db.supply_lines[entry["supply_line_id"]]
        charge = entry_charge_cents(line, entry["qty_used"])
        total_charge += charge
        append_movement(
            line,
            reason="RESTOCK_USE",
            delta_qty=-entry["qty_used"],
            charge_cents=charge,
            turnover_id=turnover["id"],
            checklist_task_id=task["id"],
        )
        project_line(line)
        touch(line, bump=True)
    return total_charge


def reverse_restock_use(task, turnover):
    """Compensating REVERSAL movements for every RESTOCK_USE this task booked."""
    booked = [m for m in ordered(db.stock_movements.values())
              if m["checklist_task_id"] == task["id"] and m["reason"] == "RESTOCK_USE"]
    for movement in booked:
        line = db.supply_lines[movement["supply_line_id"]]
        append_movement(
            line,
            reason="REVERSAL",
            delta_qty=-movement["delta_qty"],
            charge_cents=-movement["charge_cents"],
            turnover_id=movement["turnover_id"],
            checklist_task_id=task["id"],
        )
        project_line(line)
        touch(line, bump=True)
