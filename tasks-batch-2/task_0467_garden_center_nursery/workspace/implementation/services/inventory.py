"""InventoryLot computed-field reconciliation, shrink valuation, depletion."""
from db import db, touch


def recompute_lot(lot):
    """qty_on_hand = received - reserved - shrink - sold; provisional shrink value."""
    lot["qty_on_hand"] = (lot["received_qty"] - lot["reserved_qty"]
                          - lot["shrink_qty"] - lot["sold_qty"])
    # PROVISIONAL shrink valuation (lot still live)
    lot["provisional_shrink_value_cents"] = lot["shrink_qty"] * lot["unit_cost_cents"]


def maybe_deplete(lot):
    """Auto AVAILABLE -> DEPLETED when qty_on_hand == 0 and no reservations.

    On depletion the FINAL shrink valuation replaces the provisional one:
    final = (received_qty - sold_qty) * unit_cost_cents (PRD §3.2).
    Returns True if it transitioned (so caller can bump version/timestamp).
    """
    if (lot["status"] == "AVAILABLE"
            and lot["qty_on_hand"] == 0
            and lot["reserved_qty"] == 0):
        lot["status"] = "DEPLETED"
        lot["provisional_shrink_value_cents"] = (
            (lot["received_qty"] - lot["sold_qty"]) * lot["unit_cost_cents"]
        )
        touch(lot)
        return True
    return False
