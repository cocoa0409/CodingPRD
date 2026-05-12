"""Holding aggregate operations + LotEntry FIFO."""
import db
from db import holdings, lot_entries, stamp_create, stamp_update, gen_id
from clock import now, iso
from services.util import round_half_up


def get_or_create_holding(investor_id: str, fund_id: str) -> dict:
    for h in holdings.values():
        if h["investor_id"] == investor_id and h["fund_id"] == fund_id:
            return h
    h = {
        "investor_id": investor_id,
        "fund_id": fund_id,
        "shares": 0,
        "cost_basis_cents": 0,
    }
    stamp_create(h, common_fields=True)
    holdings[h["id"]] = h
    return h


def get_holding(investor_id: str, fund_id: str) -> dict:
    for h in holdings.values():
        if h["investor_id"] == investor_id and h["fund_id"] == fund_id:
            return h
    return None


def list_holdings_for_investor(investor_id: str):
    return [h for h in holdings.values() if h["investor_id"] == investor_id]


def open_lots_for(investor_id: str, fund_id: str):
    """Return OPEN lots for (investor, fund) sorted by acquired_at ascending, then by _seq for determinism."""
    holding = get_holding(investor_id, fund_id)
    if not holding:
        return []
    lots = [l for l in lot_entries.values()
            if l["holding_id"] == holding["id"] and l["status"] == "OPEN"]
    lots.sort(key=lambda l: (l["acquired_at"], l["_seq"]))
    return lots


def recompute_holding_aggregates(investor_id: str, fund_id: str):
    """After lot mutations, recompute Holding.shares and cost_basis_cents from OPEN lots."""
    holding = get_or_create_holding(investor_id, fund_id)
    lots = [l for l in lot_entries.values()
            if l["holding_id"] == holding["id"] and l["status"] == "OPEN"]
    holding["shares"] = sum(l["shares"] for l in lots)
    holding["cost_basis_cents"] = sum(l["cost_cents"] for l in lots)
    stamp_update(holding)
    return holding


def create_lot(holding_id: str, order_id: str, shares: int, cost_cents: int, acquired_at: str) -> dict:
    lot = {
        "holding_id": holding_id,
        "order_id": order_id,
        "acquired_at": acquired_at,
        "shares": shares,
        "cost_cents": cost_cents,
        "status": "OPEN",
    }
    stamp_create(lot, common_fields=False)
    lot_entries[lot["id"]] = lot
    return lot


def fifo_burn(investor_id: str, fund_id: str, requested_shares: int):
    """Burn `requested_shares` FIFO over OPEN lots. Return list of (lot, take, original_lot_shares, original_lot_cost) tuples consumed.

    Each tuple's third/fourth elements represent the lot's shares and cost BEFORE the burn so callers can compute
    proportional back-end load against original cost.
    """
    remaining = requested_shares
    consumed = []
    for lot in open_lots_for(investor_id, fund_id):
        if remaining <= 0:
            break
        original_shares = lot["shares"]
        original_cost = lot["cost_cents"]
        take = min(original_shares, remaining)
        # Proportional cost reduction
        if take == original_shares:
            burned_cost = original_cost
        else:
            burned_cost = round_half_up(original_cost * take, original_shares)
        lot["shares"] = original_shares - take
        lot["cost_cents"] = original_cost - burned_cost
        if lot["shares"] <= 0:
            lot["shares"] = 0
            lot["cost_cents"] = 0
            lot["status"] = "DEPLETED"
        consumed.append({
            "lot": lot,
            "take": take,
            "original_shares": original_shares,
            "original_cost": original_cost,
        })
        remaining -= take
    return consumed
