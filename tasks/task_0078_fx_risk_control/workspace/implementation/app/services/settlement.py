"""Multilateral netting + settlement instruction lifecycle — §3.7."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from app.numeric import round_half_up, to_decimal, ZERO
from app.store import Store, new_id, now_iso


def generate_for_counterparty(
    store: Store,
    *,
    counterparty_id: str,
    value_date: str,
    client_request_id: str,
) -> tuple[list[dict], bool]:
    """Compute multilateral netting per (counterparty, value_date).

    Returns (instructions, is_replay).
    """
    idem_key = (counterparty_id, value_date, client_request_id)
    existing_ids = store.settlement_idempotency.get(idem_key)
    if existing_ids is not None:
        # Replay — return original instructions.
        rows = [store.settlement_instructions[i] for i in existing_ids
                if i in store.settlement_instructions]
        return rows, True

    # Walk BOOKED trades for this counterparty across all trading days.
    trades = [
        t for t in store.trades.values()
        if t["counterparty_id"] == counterparty_id and t["status"] == "BOOKED"
    ]
    trades.sort(key=lambda t: (t["executed_at"], t["id"]))

    # legs[ccy] = (gross_pay, gross_receive)
    legs: dict[str, list[Decimal]] = {}

    def _bump(ccy: str, *, pay: Decimal = ZERO, receive: Decimal = ZERO) -> None:
        pair = legs.setdefault(ccy, [ZERO, ZERO])
        pair[0] = pair[0] + pay
        pair[1] = pair[1] + receive

    for trade in trades:
        pair_id = store.pair_index_by_code.get(trade["pair_code"])
        if pair_id is None:
            continue
        pair = store.currency_pairs[pair_id]
        notional_base = to_decimal(trade["notional_base"])
        entry = to_decimal(trade["entry_rate"])
        notional_quote = notional_base * entry
        if trade["side"] == "BUY":
            # We receive base, we pay quote
            _bump(pair["base_ccy"], receive=notional_base)
            _bump(pair["quote_ccy"], pay=notional_quote)
        else:
            # SELL: we pay base, we receive quote
            _bump(pair["base_ccy"], pay=notional_base)
            _bump(pair["quote_ccy"], receive=notional_quote)

    instructions: list[dict] = []
    for ccy in sorted(legs.keys()):
        gross_pay, gross_recv = legs[ccy]
        gross_pay = round_half_up(gross_pay, 2)
        gross_recv = round_half_up(gross_recv, 2)
        net = round_half_up(gross_pay - gross_recv, 2)
        ts = now_iso()
        row = {
            "id": new_id(),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "counterparty_id": counterparty_id,
            "value_date": value_date,
            "ccy": ccy,
            "gross_pay_amount": gross_pay,
            "gross_receive_amount": gross_recv,
            "net_amount": net,
            "status": "GENERATED",
            "client_request_id": client_request_id,
            "nostro_balance_delta": ZERO,
        }
        store.settlement_instructions[row["id"]] = row
        instructions.append(row)

    store.settlement_idempotency[idem_key] = [r["id"] for r in instructions]
    return instructions, False


def linked_trades_for_instruction(store: Store, instr: dict) -> list[dict]:
    """All BOOKED trades for this counterparty (status will transition together).

    The spec says "All linked Trade rows" but doesn't pin a tighter join key.
    Counterparty + value_date is the natural identity; we use counterparty_id
    plus 'still in BOOKED state' as the join filter, which matches the
    intuition that one settlement file consolidates everything that was
    BOOKED at the time of generation.
    """
    return [
        t for t in store.trades.values()
        if t["counterparty_id"] == instr["counterparty_id"]
        and t["status"] == "BOOKED"
    ]
