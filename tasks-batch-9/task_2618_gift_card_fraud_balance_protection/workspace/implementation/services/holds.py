"""Redemption holds: aggregate closed-interval capacity and the clock-driven
expiry sweep (PRD 3.5)."""
import clock
import db as dbm
from db import db
from services import cards as card_svc

HOLD_STATES = ("ACTIVE", "RELEASED", "CAPTURED", "EXPIRED")
DISPOSITIONS = ("RELEASE", "CAPTURE")


def intersecting_active(card_id, hold_start, hold_expires_at):
    """CLOSED intervals: touching endpoints count as intersecting."""
    return [
        h for h in db.holds.values()
        if h["card_id"] == card_id and h["state"] == "ACTIVE"
        and h["hold_start"] <= hold_expires_at
        and h["hold_expires_at"] >= hold_start
    ]


def capacity_exceeded(card, amount_cents, hold_start, hold_expires_at):
    """Aggregate capacity: committed + candidate must not exceed the card's
    current balance. Exactly equal fits; strictly greater is rejected."""
    committed = sum(
        h["amount_cents"]
        for h in intersecting_active(card["id"], hold_start, hold_expires_at)
    )
    return committed + amount_cents > card["current_balance_cents"]


def sweep_expired():
    """Every ACTIVE hold whose hold_expires_at is strictly before the new clock
    reading expires, in (hold_expires_at ASC, created_at ASC) order."""
    now = clock.now()
    victims = sorted(
        [h for h in db.holds.values()
         if h["state"] == "ACTIVE" and h["hold_expires_at"] < now],
        key=lambda h: (h["hold_expires_at"], h["created_at"], h["_seq"]),
    )
    affected = {}
    for hold in victims:
        hold["state"] = "EXPIRED"
        dbm.touch(hold)
        card = db.cards.get(hold["card_id"])
        if card is not None:
            affected[card["id"]] = card
    for card in dbm.by_created(list(affected.values())):
        card_svc.recompute(card)
        dbm.touch(card)
    return len(victims)
