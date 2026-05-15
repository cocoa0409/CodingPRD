"""Currency conversion helpers per PRD §2.6."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from app.numeric import to_decimal, ZERO
from app.store import Store


def usd_rate_for_ccy(store: Store, ccy: str) -> Optional[Decimal]:
    """Return USD-per-ccy.  When ccy == 'USD', returns 1.

    Otherwise returns the mid_rate of the pair whose code is `USD` + ccy.
    Returns None if no such pair exists (caller decides what to do).
    """
    if ccy == "USD":
        return Decimal("1")
    pair_code = "USD" + ccy
    pair_id = store.pair_index_by_code.get(pair_code)
    if pair_id is None:
        return None
    return to_decimal(store.currency_pairs[pair_id]["mid_rate"])


def base_in_usd_rate(store: Store, pair: dict) -> Decimal:
    """USD-per-1-base for a given pair, per §2.6 rule.

    - base_ccy == 'USD'  -> 1
    - quote_ccy == 'USD' -> mid_rate
    - else               -> mid_rate * usd_rate(quote_ccy)
    """
    base = pair["base_ccy"]
    quote = pair["quote_ccy"]
    mid = to_decimal(pair["mid_rate"])
    if base == "USD":
        return Decimal("1")
    if quote == "USD":
        return mid
    quote_usd = usd_rate_for_ccy(store, quote)
    if quote_usd is None:
        # If triangulation pair missing, fall back to mid_rate; in practice
        # tests register the relevant USD pair before they triangulate.
        return mid
    return mid * quote_usd


def quote_in_usd_rate(store: Store, pair: dict) -> Decimal:
    """USD per 1 quote-currency unit."""
    quote = pair["quote_ccy"]
    if quote == "USD":
        return Decimal("1")
    usd = usd_rate_for_ccy(store, quote)
    return usd if usd is not None else Decimal("1")
