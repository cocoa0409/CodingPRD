"""Counterparty rating band / credit limit derivation per §3.6."""
from __future__ import annotations

from decimal import Decimal

from app.numeric import to_decimal


EXTERNAL_BAND = {
    "AAA": "INVESTMENT",
    "AA": "INVESTMENT",
    "A": "STANDARD",
    "BBB": "STANDARD",
    "BB": "SPECULATIVE",
    "B": "SPECULATIVE",
    "CCC": "WATCH",
    "NR": "WATCH",
}

BAND_SEVERITY = {"INVESTMENT": 0, "STANDARD": 1, "SPECULATIVE": 2, "WATCH": 3}

CREDIT_TIER_USD = {
    "INVESTMENT": Decimal("100000000.00"),
    "STANDARD": Decimal("50000000.00"),
    "SPECULATIVE": Decimal("10000000.00"),
    "WATCH": Decimal("1000000.00"),
}


def internal_band(score: int) -> str:
    if score >= 80:
        return "INVESTMENT"
    if score >= 60:
        return "STANDARD"
    if score >= 40:
        return "SPECULATIVE"
    return "WATCH"


def derive_band(external_rating: str, internal_score: int) -> str:
    bx = EXTERNAL_BAND.get(external_rating, "WATCH")
    bi = internal_band(internal_score)
    return max(bx, bi, key=lambda b: BAND_SEVERITY[b])


def credit_limit_for_band(band: str) -> Decimal:
    return CREDIT_TIER_USD[band]


def recompute_counterparty(row: dict) -> None:
    row["rating_band"] = derive_band(row["external_rating"], row["internal_score"])
    row["credit_limit_usd"] = credit_limit_for_band(row["rating_band"])
    row["on_watchlist"] = row["rating_band"] == "WATCH"
