"""Reseller listing validation and the freeze-driven block cascade (PRD 3.8)."""
import db as dbm
from db import db

LISTING_STATES = ("SUBMITTED", "VALIDATED", "REJECTED", "BLOCKED")
BLOCK_REASONS = ("CARD_NOT_ACTIVE", "CARD_RISK_POSTURE", "BALANCE_MISMATCH",
                 "DRAIN_SCORE")


def validation_decision(listing, card, policy):
    """Fixed check order, first match wins (PRD 3.8)."""
    if card["activation_state"] != "ACTIVE":
        return "REJECTED", "CARD_NOT_ACTIVE"
    if card["risk_posture"] in ("RESTRICTED", "FROZEN"):
        return "BLOCKED", "CARD_RISK_POSTURE"
    if listing["listed_balance_cents"] != card["current_balance_cents"]:
        return "REJECTED", "BALANCE_MISMATCH"
    if card["drain_risk_score_inquiry"] >= policy["drain_restrict_score_threshold"]:
        return "BLOCKED", "DRAIN_SCORE"
    return "VALIDATED", None


def block_validated_listings(card):
    """Every VALIDATED listing on the card becomes BLOCKED with block_reason
    CARD_RISK_POSTURE, processed in created_at ASC order."""
    victims = dbm.by_created([
        l for l in db.listings.values()
        if l["card_id"] == card["id"] and l["state"] == "VALIDATED"
    ])
    for listing in victims:
        listing["state"] = "BLOCKED"
        listing["block_reason"] = "CARD_RISK_POSTURE"
        dbm.touch(listing)
    return victims
