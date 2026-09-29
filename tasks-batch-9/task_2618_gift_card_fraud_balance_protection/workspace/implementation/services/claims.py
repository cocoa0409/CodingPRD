"""Victim claim reissue arithmetic (PRD 3.9)."""
import db as dbm
from db import db
from services import cards as card_svc
from services.money import apply_bps

CLAIM_STATES = ("SUBMITTED", "EVIDENCE_REQUESTED", "APPROVED", "DENIED", "RESCINDED")
EVIDENCE_KINDS = ("PURCHASE_RECEIPT", "PACKAGING_PHOTO")
DECISIONS = ("APPROVE", "DENY")


def unauthorized_lines(claim):
    """Unreversed REDEMPTION events on the card at or after purchased_at,
    in replay order."""
    reversed_ids = card_svc.reversed_event_ids()
    return [
        e for e in card_svc.card_events(claim["card_id"])
        if e["type"] == "REDEMPTION"
        and e["id"] not in reversed_ids
        and e["occurred_at"] >= claim["purchased_at"]
    ]


def gross_reissue(lines, policy):
    """Per-line recovery rounded half up, then summed - never the other way."""
    return sum(
        apply_bps(line["amount_cents"], policy["recovery_factor_bps"])
        for line in lines
    )


def reissue_figures(claim, card, policy):
    lines = unauthorized_lines(claim)
    gross = gross_reissue(lines, policy)
    reissue = min(gross, claim["disputed_amount_cents"])
    residual = card["current_balance_cents"]
    return len(lines), gross, reissue, residual
