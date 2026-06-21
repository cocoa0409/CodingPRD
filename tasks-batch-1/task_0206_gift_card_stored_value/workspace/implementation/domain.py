"""Domain helpers shared across routes: campaign status sync, dormancy month
math, lifecycle auto-transitions, redemption reversal cascade. Each rule
traces to a PRD §3 sentence."""

from db import db
from core import (
    settled_balance,
    post_ledger,
    touch,
    parse_iso,
)


# ---------------------------------------------------------------------------
# Campaign status sync (PRD §3.1).
# ---------------------------------------------------------------------------


def compute_campaign_status(campaign, now):
    """Pure status derivation against `now` (an aware UTC datetime).
    Half-open [window_start, window_end)."""
    start = parse_iso(campaign["window_start"])
    end = parse_iso(campaign["window_end"])
    if now >= end:
        return "ENDED"
    if now >= start:
        return "ACTIVE"
    return "SCHEDULED"


def sync_campaign(campaign, now):
    new_status = compute_campaign_status(campaign, now)
    if new_status != campaign["status"]:
        campaign["status"] = new_status
        touch(campaign)
    return campaign


def sync_all_campaigns(now):
    """System clock-advance recompute of every campaign (PRD §3.10)."""
    for c in db.campaigns.values():
        sync_campaign(c, now)


def active_campaign_for_program(program_id, now):
    """The ACTIVE campaign in this program at `now`, if any. Recomputes status
    against the clock so a SCHEDULED campaign whose window has opened counts as
    ACTIVE at the reload instant (PRD §3.3)."""
    for c in db.campaigns.values():
        if c["program_id"] != program_id:
            continue
        if compute_campaign_status(c, now) == "ACTIVE":
            return c
    return None


# ---------------------------------------------------------------------------
# Lifecycle auto-transitions on balance change (PRD §2.9).
# ---------------------------------------------------------------------------


def apply_balance_lifecycle(card):
    """After a card's balance changes, reconcile ACTIVE<->EXHAUSTED.
    Only applies to cards currently in ACTIVE/EXHAUSTED; terminal and INACTIVE
    cards are untouched."""
    status = card["lifecycle_status"]
    if status not in ("ACTIVE", "EXHAUSTED"):
        return
    bal = settled_balance(card["id"])
    if bal == 0 and status == "ACTIVE":
        card["lifecycle_status"] = "EXHAUSTED"
        touch(card)
    elif bal > 0 and status == "EXHAUSTED":
        card["lifecycle_status"] = "ACTIVE"
        touch(card)


# ---------------------------------------------------------------------------
# Dormancy month math (PRD §3.8): floor of whole months elapsed.
# ---------------------------------------------------------------------------


def whole_months_between(start_iso, now):
    """Floor of whole calendar months between start (ISO str) and now (aware
    UTC datetime)."""
    start = parse_iso(start_iso)
    months = (now.year - start.year) * 12 + (now.month - start.month)
    # If the day-of-month (and time within the day) hasn't yet been reached,
    # the current month is not complete -> subtract one.
    if (now.day, now.hour, now.minute, now.second, now.microsecond) < (
        start.day, start.hour, start.minute, start.second, start.microsecond
    ):
        months -= 1
    return max(months, 0)


def waiver_covers(card_id, now):
    """True if an ACTIVE DormancyWaiver on the card covers `now` (closed
    interval [window_start, window_end], PRD §3.8)."""
    for w in db.dormancy_waivers.values():
        if w["card_id"] != card_id or w["status"] != "ACTIVE":
            continue
        start = parse_iso(w["window_start"])
        end = parse_iso(w["window_end"])
        if start <= now <= end:
            return True
    return False


# ---------------------------------------------------------------------------
# Redemption reversal cascade (PRD §3.6): drive a SETTLED redemption to VOIDED,
# posting a REVERSAL credit per leg and reviving exhausted cards.
# ---------------------------------------------------------------------------


def reverse_redemption(redemption, source_ref_id):
    legs = [
        leg for leg in db.redemption_legs.values()
        if leg["redemption_id"] == redemption["id"]
    ]
    for leg in legs:
        original = db.ledger_entries.get(leg["ledger_entry_id"])
        card = db.cards[leg["card_id"]]
        # REVERSAL credit cancels the leg's REDEEM debit (positive amount).
        post_ledger(
            card,
            "REVERSAL",
            leg["leg_amount_cents"],
            source_ref_id=source_ref_id,
            reverses_entry_id=leg["ledger_entry_id"],
        )
        if original is not None:
            original["status"] = "REVERSED"
        apply_balance_lifecycle(card)
    redemption["status"] = "VOIDED"
    touch(redemption)
