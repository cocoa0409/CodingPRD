"""Grind-run blend derivation and the trim-lot pound ledger (PRD §3.5, §2.6)."""

from calc import ZERO, rhu
from db import db, mark


def inputs_of_run(run_id):
    rows = [row for row in db.grind_inputs.values() if row["grind_run_id"] == run_id]
    return sorted(rows, key=lambda row: row["input_seq"])


def derive_blend(run):
    """Re-derive batch weight, blended lean, blend cost and the origin label."""
    inputs = inputs_of_run(run["id"])
    batch = ZERO
    lean_weighted = ZERO
    cost_weighted = ZERO
    origins = []
    for row in inputs:
        lot = db.trim_lots.get(row["trim_lot_id"])
        pounds = row["weight_lb"]
        batch += pounds
        if lot is not None:
            lean = lot.get("lean_pct")
            lean_weighted += pounds * (lean if lean is not None else ZERO)
            cost_weighted += pounds * lot["cost_per_lb_cents"]
            if lot["country_of_origin"] not in origins:
                origins.append(lot["country_of_origin"])

    run["batch_weight_lb"] = rhu(batch, 2)
    if batch > 0:
        run["blended_lean_pct"] = rhu(lean_weighted / batch, 2)
        run["blend_cost_per_lb_cents"] = rhu(cost_weighted / batch, 4)
    else:
        run["blended_lean_pct"] = rhu(0, 2)
        run["blend_cost_per_lb_cents"] = rhu(0, 4)

    if not inputs:
        run["coo_label"] = "PENDING"
    elif len(origins) == 1:
        run["coo_label"] = origins[0]
    else:
        run["coo_label"] = "MULTIPLE"
    mark(run)


# --------------------------------------------------------------------------
# the trim-lot four-bucket ledger
# --------------------------------------------------------------------------

def commit_pounds(lot, pounds):
    lot["allocated_lb"] = rhu(lot["allocated_lb"] + pounds, 2)
    lot["remaining_lb"] = rhu(lot["remaining_lb"] - pounds, 2)
    lot["status"] = "FULLY_COMMITTED" if lot["remaining_lb"] == 0 else "PARTIALLY_COMMITTED"
    mark(lot)


def consume_pounds(lot, pounds):
    lot["allocated_lb"] = rhu(lot["allocated_lb"] - pounds, 2)
    lot["consumed_lb"] = rhu(lot["consumed_lb"] + pounds, 2)
    lot["status"] = "CONSUMED" if lot["remaining_lb"] == 0 else "PARTIALLY_COMMITTED"
    mark(lot)


def restore_pounds(lot, pounds):
    lot["allocated_lb"] = rhu(lot["allocated_lb"] - pounds, 2)
    lot["remaining_lb"] = rhu(lot["remaining_lb"] + pounds, 2)
    lot["status"] = "AVAILABLE" if lot["allocated_lb"] == 0 else "PARTIALLY_COMMITTED"
    mark(lot)


def discard_lot(lot):
    lot["discarded_lb"] = rhu(lot["discarded_lb"] + lot["remaining_lb"], 2)
    lot["remaining_lb"] = rhu(0, 2)
    lot["status"] = "DISCARDED"
    mark(lot)
