"""Resource serialisation.

Derived fields (a cold room's occupancy and posture, a contract's slot ledger, a
customer's chargeback balance) are re-derived at read time so the conserved
quantities of PRD 2.9 can never drift from their definitions.
"""
from datetime import datetime
from decimal import Decimal

import clock
import services


def value(raw):
    if isinstance(raw, datetime):
        return clock.fmt(raw)
    if isinstance(raw, Decimal):
        return float(raw)
    if isinstance(raw, (list, tuple)):
        return [value(item) for item in raw]
    return raw


def ser(row, **overlay):
    out = {}
    for key, raw in row.items():
        if key.startswith("_"):
            continue
        out[key] = value(raw)
    for key, raw in overlay.items():
        out[key] = value(raw)
    return out


plain = ser


def customer(row):
    return ser(row, chargeback_balance_cents=services.pending_balance(row["id"]))


def cold_room(row):
    occupied = services.room_occupancy(row["id"])
    return ser(row,
               occupied_pallets=occupied,
               capacity_state=services.posture(occupied, row["capacity_pallets"]))


def contract(row):
    return ser(row, **services.contract_ledger(row))
