"""Offer negotiation-state projection from append-only CounterRounds."""
from db import db


def offer_rounds(offer):
    rounds = [r for r in db.counter_rounds.values() if r["offer_id"] == offer["id"]]
    rounds.sort(key=lambda r: r["round_index"])
    return rounds


def offer_projection(offer):
    """Replay CounterRounds in round_index order to derive negotiation state."""
    rounds = offer_rounds(offer)
    round_count = len(rounds)
    if round_count == 0:
        return {
            "current_price_cents": offer["initial_price_cents"],
            "current_party": "SELLER",
            "round_count": 0,
        }
    last = rounds[-1]
    current_party = "BUYER" if last["by_party"] == "SELLER" else "SELLER"
    return {
        "current_price_cents": last["counter_price_cents"],
        "current_party": current_party,
        "round_count": round_count,
    }
