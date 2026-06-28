"""Supply lot FEFO selection, reservation, consumption, release (PRD §3.10).

A candidate lot for a line must:
  - item_kind match the line (DRIP_BASE for the drip, ADDON for an add-on),
  - tier_or_code equal the line key (drip tier, or add-on code),
  - status == AVAILABLE,
  - expires_at strictly after the appointment start_at (half-open window),
  - have at least one free unit (total - reserved - consumed >= 1).
FEFO: sort by expires_at asc, tie-break created_at asc, pick first.
"""
import db
from errors import err, ERR_SUPPLY_UNAVAILABLE
from helpers import refresh_supply_lot


def free_units(lot):
    return lot["units_total"] - lot["units_reserved"] - lot["units_consumed"]


def _candidates(item_kind, key, start_at):
    out = []
    for lot in db.supply_lots.values():
        refresh_supply_lot(lot)
        if lot["item_kind"] != item_kind:
            continue
        if lot["tier_or_code"] != key:
            continue
        if lot["status"] != "AVAILABLE":
            continue
        if not (start_at < lot["expires_at"]):
            continue
        if free_units(lot) < 1:
            continue
        out.append(lot)
    out.sort(key=lambda l: (l["expires_at"], l["created_at"], l["_seq"]))
    return out


def build_lines(menu_item, addon_records):
    """Return the ordered line list as (item_kind, key) tuples: drip first,
    then each add-on in request order."""
    lines = [("DRIP_BASE", menu_item["tier"])]
    for ao in addon_records:
        lines.append(("ADDON", ao["code"]))
    return lines


def plan_reservations(lines, start_at):
    """Choose one lot per line via FEFO, treating prior picks in this same
    plan as already reserving a unit. Raises ERR_SUPPLY_UNAVAILABLE if any
    line has no candidate. Returns the ordered list of chosen lot ids."""
    pending = {}  # lot_id -> units tentatively reserved in this plan
    chosen = []
    for item_kind, key in lines:
        cands = _candidates(item_kind, key, start_at)
        picked = None
        for lot in cands:
            if free_units(lot) - pending.get(lot["id"], 0) >= 1:
                picked = lot
                break
        if picked is None:
            raise err(ERR_SUPPLY_UNAVAILABLE,
                      "No available supply for line %s/%s." % (item_kind, key))
        pending[picked["id"]] = pending.get(picked["id"], 0) + 1
        chosen.append(picked["id"])
    return chosen


def apply_reservations(chosen_lot_ids):
    """Commit reservations: increment units_reserved by 1 per chosen line."""
    for lot_id in chosen_lot_ids:
        lot = db.supply_lots[lot_id]
        lot["units_reserved"] += 1
