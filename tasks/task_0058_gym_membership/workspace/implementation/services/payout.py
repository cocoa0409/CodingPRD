"""Payout cycle open/close."""
from clock import now
from db import state, new_id, next_order, bump
from errors import raise_err
from .calc import mul_bp_round_half_up


def open_cycle(cycle_start, cycle_end):
    p = {
        "id": new_id(),
        "cycle_start": cycle_start,
        "cycle_end": cycle_end,
        "closed_at": None,
        "status": "OPEN",
        "created_at": now(),
        "_order": next_order(),
    }
    state["payout_cycles"][p["id"]] = p
    return p


def close_cycle(cycle):
    if cycle["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "cycle not OPEN")
    if now() < cycle["cycle_end"]:
        raise_err("ERR_PAYOUT_CYCLE_OPEN", "cycle not yet closed")
    cs, ce = cycle["cycle_start"], cycle["cycle_end"]
    # Group commission rows by trainer
    trainer_ids = set()
    for r in state["commission_records"].values():
        trainer_ids.add(r["trainer_id"])
    for tid in trainer_ids:
        # Step 1: gather rows to attach (kind in SESSION/PACKAGE_SALE/REVERSAL,
        # within window, payout_cycle_id is None)
        gather = []
        for r in state["commission_records"].values():
            if r["trainer_id"] != tid:
                continue
            if r["kind"] not in ("SESSION", "PACKAGE_SALE", "REVERSAL"):
                continue
            if r.get("payout_cycle_id") is not None:
                continue
            if not (cs <= r["created_at"] < ce):
                continue
            gather.append(r)
        # Step 2: recompute tier per cycle session count
        session_count = sum(
            1 for b in state["pt_bookings"].values()
            if b["trainer_id"] == tid and b["status"] == "COMPLETED"
            and cs <= b["scheduled_starts_at"] < ce
        )
        if session_count >= 80:
            new_tier = "GOLD"
            tier_bp = 2000
        elif session_count >= 40:
            new_tier = "SILVER"
            tier_bp = 1000
        else:
            new_tier = "BRONZE"
            tier_bp = 0
        trainer = state["trainers"].get(tid)
        if trainer:
            trainer["tier"] = new_tier
            bump(trainer)
        # Step 3: tier bonus = sum of SESSION rows in window * tier_bp / 10000
        session_sum = sum(
            r["amount_cents"] for r in state["commission_records"].values()
            if r["trainer_id"] == tid and r["kind"] == "SESSION"
            and cs <= r["created_at"] < ce
        )
        bonus = mul_bp_round_half_up(session_sum, tier_bp)
        if bonus != 0 or tier_bp > 0:
            # Append tier bonus row (even when 0 for SILVER/GOLD? spec implies append unconditionally when tier_bp > 0)
            tb = {
                "id": new_id(),
                "trainer_id": tid,
                "kind": "TIER_BONUS",
                "amount_cents": bonus,
                "ref_entity": f"PayoutCycle:{cycle['id']}",
                "payout_cycle_id": cycle["id"],
                "created_at": now(),
                "_order": next_order(),
            }
            state["commission_records"][tb["id"]] = tb
        # Stamp gathered rows
        for r in gather:
            r["payout_cycle_id"] = cycle["id"]
    cycle["status"] = "CLOSED"
    cycle["closed_at"] = now()
    return cycle
