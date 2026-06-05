"""Synchronous deadline evaluator for ExchangeAccount (PRD §3.7).

Two automatic transitions to FAILED:
  - OPEN -> FAILED when now > identification_deadline AND replacement_property_identified is false
  - IDENTIFIED -> FAILED when now > exchange_deadline

Evaluated on any read or related write that observes the deadline.
"""
from __future__ import annotations

from clock import CLOCK, now_iso
from db import DB_INSTANCE


def evaluate_exchange_account(x: dict) -> dict:
    """Mutate the row in-place if a deadline has elapsed; return the (possibly updated) row.

    Per scaffold side_effects: each FAILED transition bumps version by 1.
    """
    if x["status"] in ("COMPLETED", "FAILED"):
        return x
    now = CLOCK.now()
    if x["status"] == "OPEN":
        if now > x["identification_deadline"] and x["replacement_property_identified"] is False:
            x["status"] = "FAILED"
            x["version"] += 1
            x["updated_at"] = CLOCK.now()
            return x
    if x["status"] == "IDENTIFIED":
        if now > x["exchange_deadline"]:
            x["status"] = "FAILED"
            x["version"] += 1
            x["updated_at"] = CLOCK.now()
            return x
    return x


def evaluate_all_exchanges() -> None:
    for x in list(DB_INSTANCE.exchange_accounts.values()):
        evaluate_exchange_account(x)
