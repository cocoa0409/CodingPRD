"""Position / Lot / Disposal mechanics and cost-basis calc (PRD §3.5, SCAFFOLD cost_basis_disposal).

A Position is unique per (account_id, security_id). Lots are opened by BUY fills;
disposals consume lots (FIFO) or the position average (AVERAGE) on SELL fills."""
from decimal import Decimal

import constants
from db import db, new_id, created_ts
from models import _base_full, touch
from money import round_half_up, truncate_shares, shares_str


def get_or_create_position(account_id, security_id, cost_basis_method="FIFO"):
    """Find the (account, security) position or create it. cost_basis_method is
    pinned at first open (default FIFO, PRD §3.5)."""
    for p in db.positions.values():
        if p["account_id"] == account_id and p["security_id"] == security_id:
            return p
    rec = _base_full()
    rec.update({
        "account_id": account_id,
        "security_id": security_id,
        "quantity": 0.0,
        "average_cost_cents": 0,
        "cost_basis_method": cost_basis_method if cost_basis_method in ("FIFO", "AVERAGE") else "FIFO",
        "market_value_cents": 0,
        "realized_pl_cents": 0,
        "drip_enabled": False,
    })
    db.positions[rec["id"]] = rec
    return rec


def open_lots(position_id):
    """OPEN / PARTIALLY_CLOSED lots for a position, ordered oldest-first
    (ascending acquired_at then created_at/_seq) — FIFO key (PRD §3.5)."""
    lots = [l for l in db.lots.values()
            if l["position_id"] == position_id and l["status"] in ("OPEN", "PARTIALLY_CLOSED")]
    lots.sort(key=lambda l: (l["acquired_at"], l["_seq"]))
    return lots


def recompute_position(p):
    """Recompute quantity and average_cost from open lots (PRD §3.5)."""
    lots = open_lots(p["id"])
    total_qty = Decimal(0)
    total_basis = Decimal(0)
    for l in lots:
        rq = Decimal(str(l["remaining_quantity"]))
        total_qty += rq
        total_basis += rq * Decimal(l["cost_per_share_cents"])
    p["quantity"] = shares_str(total_qty)
    if total_qty > 0:
        p["average_cost_cents"] = round_half_up(total_basis / total_qty)
    else:
        p["average_cost_cents"] = 0
    from services.account import recompute_position_market_value
    recompute_position_market_value(p)


def open_lot(position_id, fill, quantity, gross_value_cents):
    """Open a new Lot from a BUY fill (PRD §3.5)."""
    rec = _base_full()
    cps = round_half_up(Decimal(gross_value_cents) / Decimal(str(quantity)))
    rec.update({
        "position_id": position_id,
        "acquired_at": created_ts(),
        "original_quantity": shares_str(quantity),
        "remaining_quantity": shares_str(quantity),
        "cost_per_share_cents": cps,
        "status": "OPEN",
    })
    db.lots[rec["id"]] = rec
    return rec


def dispose_shares(p, sell_fill, sell_qty, fill_price_cents):
    """Create Disposal record(s) for a SELL fill, consuming lots (FIFO) or the
    position average (AVERAGE). Returns the list of created disposals.
    Updates lots, position quantity, realized P/L (PRD §3.5)."""
    from timeutil import parse_iso, date_floor
    method = p["cost_basis_method"]
    disposals = []
    proceeds_total = 0
    realized_total = 0
    now = db.clock

    if method == "AVERAGE":
        avg = p["average_cost_cents"]
        proceeds = round_half_up(Decimal(str(sell_qty)) * Decimal(fill_price_cents))
        cost_basis = round_half_up(Decimal(str(sell_qty)) * Decimal(avg))
        realized = proceeds - cost_basis
        # term from earliest contributing lot's acquired_at
        lots = open_lots(p["id"])
        earliest = min(lots, key=lambda l: (l["acquired_at"], l["_seq"])) if lots else None
        term = _term(earliest, now) if earliest else "SHORT"
        d = _make_disposal(p["id"], sell_fill["id"], None, sell_qty, proceeds,
                           cost_basis, realized, term)
        disposals.append(d)
        proceeds_total += proceeds
        realized_total += realized
        # consume lots oldest-first to keep remaining_quantity consistent
        _consume_lots_fifo(p, sell_qty)
    else:  # FIFO
        remaining = Decimal(str(sell_qty))
        for lot in open_lots(p["id"]):
            if remaining <= 0:
                break
            avail = Decimal(str(lot["remaining_quantity"]))
            take = min(avail, remaining)
            proceeds = round_half_up(take * Decimal(fill_price_cents))
            cost_basis = round_half_up(take * Decimal(lot["cost_per_share_cents"]))
            realized = proceeds - cost_basis
            term = _term(lot, now)
            d = _make_disposal(p["id"], sell_fill["id"], lot["id"],
                               shares_str(take), proceeds, cost_basis, realized, term)
            disposals.append(d)
            proceeds_total += proceeds
            realized_total += realized
            new_remaining = avail - take
            lot["remaining_quantity"] = shares_str(new_remaining)
            if new_remaining <= 0:
                lot["status"] = "CLOSED"
            else:
                lot["status"] = "PARTIALLY_CLOSED"
            touch(lot)
            remaining -= take

    p["realized_pl_cents"] = p["realized_pl_cents"] + realized_total
    recompute_position(p)
    touch(p)
    return disposals


def _consume_lots_fifo(p, qty):
    """Reduce remaining_quantity across open lots oldest-first (for AVERAGE method
    bookkeeping of share counts; basis already computed at position average)."""
    remaining = Decimal(str(qty))
    for lot in open_lots(p["id"]):
        if remaining <= 0:
            break
        avail = Decimal(str(lot["remaining_quantity"]))
        take = min(avail, remaining)
        new_remaining = avail - take
        lot["remaining_quantity"] = shares_str(new_remaining)
        if new_remaining <= 0:
            lot["status"] = "CLOSED"
        else:
            lot["status"] = "PARTIALLY_CLOSED"
        touch(lot)
        remaining -= take


def _term(lot, now):
    from timeutil import parse_iso
    acquired = parse_iso(lot["acquired_at"])
    held_days = (now - acquired).total_seconds() / 86400.0
    return "SHORT" if held_days <= constants.LONG_TERM_DAYS else "LONG"


def _make_disposal(position_id, fill_id, lot_id, qty, proceeds, cost_basis, realized, term):
    rec = _base_full()
    rec.update({
        "position_id": position_id,
        "fill_id": fill_id,
        "lot_id": lot_id,
        "quantity": qty,
        "proceeds_cents": proceeds,
        "cost_basis_cents": cost_basis,
        "realized_pl_cents": realized,
        "term": term,
    })
    db.disposals[rec["id"]] = rec
    return rec
