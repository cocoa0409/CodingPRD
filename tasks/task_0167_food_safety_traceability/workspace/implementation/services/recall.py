"""Mock recall trace and exposure-quantity calculation (PRD §3.9)."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import db
from services.genealogy import one_up_source_lot_ids, downstream_finished_closure


def _covered_by_disposed_hold(lot_id: str) -> bool:
    """True when the lot is in the covered set of any DISPOSED hold (PRD §3.9).

    The covered set is recomputed from current genealogy for the disposed hold's
    target; membership is a genealogy property.
    """
    for h in db.hold_orders.values():
        if h.get("status") != "DISPOSED":
            continue
        target = h["target_lot_id"]
        if lot_id == target:
            return True
        if lot_id in downstream_finished_closure(target):
            return True
    return False


def recall_trace(lot_id: str) -> dict:
    one_up = one_up_source_lot_ids(lot_id)
    one_down = downstream_finished_closure(lot_id)

    disposed = _covered_by_disposed_hold(lot_id)

    total = Decimal("0")
    if not disposed:
        # provisional: sum received_qty over ALL downstream finished lots.
        variant = "provisional_exposure"
        for fid in one_down:
            fl = db.lots.get(fid)
            if fl is not None:
                total += Decimal(str(fl["received_qty"]))
    else:
        # finalized: sum received_qty over downstream finished lots EXCLUDING
        # any currently DESTROYED.
        variant = "finalized_exposure"
        for fid in one_down:
            fl = db.lots.get(fid)
            if fl is not None and fl["status"] != "DESTROYED":
                total += Decimal(str(fl["received_qty"]))

    exposure_qty = float(total.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))

    return {
        "recalled_lot_id": lot_id,
        "one_up_source_lot_ids": one_up,
        "one_down_finished_lot_ids": one_down,
        "exposure_variant": variant,
        "exposure_qty": exposure_qty,
    }
