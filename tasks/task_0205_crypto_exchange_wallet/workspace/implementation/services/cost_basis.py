"""Cost-basis lot creation and FIFO/HIFO disposal (§3.10, calc realized_gain_on_disposal)."""
from db import db, new_id, next_seq
from numeric import D, round_half_up, round_usd
from services.common import touch


def create_lot(account_id, asset, origin_type, origin_id, quantity, unit_cost_usd, acquired_at, asset_decimals):
    now = db.clock.now()
    qty = round_half_up(quantity, asset_decimals)
    lot = {
        "id": new_id(),
        "account_id": account_id,
        "asset": asset,
        "origin_type": origin_type,
        "origin_id": origin_id,
        "acquired_at": acquired_at,
        "original_quantity": qty,
        "remaining_quantity": qty,
        "unit_cost_usd": D(unit_cost_usd),
        "status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db.cost_basis_lots[lot["id"]] = lot
    return lot


def _ordered_open_lots(account_id, asset, method):
    lots = [
        l for l in db.cost_basis_lots.values()
        if l["account_id"] == account_id and l["asset"] == asset
        and l["status"] == "OPEN" and D(l["remaining_quantity"]) > 0
    ]
    if method == "FIFO":
        lots.sort(key=lambda l: (l["acquired_at"], l["created_at"], l["_seq"]))
    else:  # HIFO
        lots.sort(key=lambda l: (-D(l["unit_cost_usd"]), l["acquired_at"], l["_seq"]))
    return lots


def dispose(account_id, asset, quantity, proceeds_usd, method, asset_decimals):
    """Consume open lots for `quantity` of `asset`. Returns realized_gain_usd.

    Mutates lots in place (decrements remaining_quantity, flips to DEPLETED).
    """
    remaining = round_half_up(quantity, asset_decimals)
    cost_consumed = D(0)
    for lot in _ordered_open_lots(account_id, asset, method):
        if remaining <= 0:
            break
        lot_remaining = D(lot["remaining_quantity"])
        take = lot_remaining if lot_remaining < remaining else remaining
        cost_consumed += take * D(lot["unit_cost_usd"])
        new_remaining = round_half_up(lot_remaining - take, asset_decimals)
        lot["remaining_quantity"] = new_remaining
        if new_remaining <= 0:
            lot["status"] = "DEPLETED"
        touch(lot)
        remaining = round_half_up(remaining - take, asset_decimals)
    cost_consumed = round_usd(cost_consumed)
    realized = round_usd(D(proceeds_usd) - cost_consumed)
    return realized
