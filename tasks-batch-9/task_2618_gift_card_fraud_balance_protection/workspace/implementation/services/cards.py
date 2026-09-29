"""GiftCard ledger projection, funding edges and posture ladder (PRD 3.4)."""
import random
from datetime import timedelta
from decimal import Decimal

import clock
import db as dbm
from db import db

CREDIT_TYPES = ("ACTIVATION_LOAD", "REDEMPTION_REVERSAL", "REISSUE_CREDIT",
                "REISSUE_DEBIT_REVERSAL")
DEBIT_TYPES = ("REDEMPTION", "REISSUE_DEBIT", "REISSUE_CREDIT_REVERSAL")
EVENT_TYPES = CREDIT_TYPES + DEBIT_TYPES

ACTIVATION_STATES = ("INACTIVE", "ACTIVE", "DEPLETED", "CLOSED", "VOIDED")
POSTURES = ("CLEAR", "WATCH", "RESTRICTED", "FROZEN")
POSTURE_RANK = {"CLEAR": 0, "WATCH": 1, "RESTRICTED": 2, "FROZEN": 3}
CHANNELS = ("PHYSICAL", "DIGITAL")


def signed_amount(event_type, amount_cents):
    return amount_cents if event_type in CREDIT_TYPES else -amount_cents


def replay_order(events):
    """occurred_at ASC, created_at ASC (PRD 3.4)."""
    return sorted(events, key=lambda e: (e["occurred_at"], e["created_at"], e["_seq"]))


def card_events(card_id):
    return replay_order([e for e in db.events.values() if e["card_id"] == card_id])


def reversed_event_ids():
    return set(
        e["reverses_event_id"] for e in db.events.values() if e.get("reverses_event_id")
    )


def generate_masked_pan():
    existing = set(
        c.get("card_number_masked") for c in db.cards.values() if c.get("card_number_masked")
    )
    while True:
        candidate = "****-****-****-%04d" % random.randint(0, 9999)
        if candidate not in existing:
            return candidate


def new_card(channel, store_id=None, rack_id=None, card_number_masked=None,
             reissued_from_card_id=None, activation_state="INACTIVE",
             risk_posture="CLEAR"):
    rec = dbm.record({
        "channel": channel,
        "store_id": store_id,
        "rack_id": rack_id,
        "reissued_from_card_id": reissued_from_card_id,
        "card_number_masked": card_number_masked or generate_masked_pan(),
        "activation_state": activation_state,
        "risk_posture": risk_posture,
        "face_value_cents": 0,
        "current_balance_cents": 0,
        "held_amount_cents": 0,
        "available_balance_cents": 0,
        "total_loaded_cents": 0,
        "total_redeemed_cents": 0,
        "drawdown_ratio": 0.00,
        "distinct_merchant_count": 0,
        "recent_redemption_count": 0,
        "drain_risk_score_inquiry": 0,
        "drain_risk_score_redemption": 0,
        "activated_at": None,
        "closed_at": None,
    })
    rec["_drawdown"] = Decimal("0.00")
    db.cards[rec["id"]] = rec
    return rec


def append_event(card, event_type, amount_cents, created_by_user_id,
                 merchant_store_id=None, reverses_event_id=None,
                 pos_terminal_id=None, memo=None):
    rec = dbm.audit_record({
        "card_id": card["id"],
        "merchant_store_id": merchant_store_id,
        "reverses_event_id": reverses_event_id,
        "type": event_type,
        "amount_cents": amount_cents,
        "signed_amount_cents": signed_amount(event_type, amount_cents),
        "occurred_at": clock.now(),
        "pos_terminal_id": pos_terminal_id,
        "memo": memo,
        "created_by_user_id": created_by_user_id,
    })
    db.events[rec["id"]] = rec
    return rec


def recompute(card):
    """Re-derive the whole projection from the card's ledger and holds. This is
    a pure recomputation: it never touches version or updated_at."""
    policy = dbm.policy()
    now = clock.now()
    events = card_events(card["id"])
    reversed_ids = reversed_event_ids()

    current = sum(e["signed_amount_cents"] for e in events)
    loaded = sum(e["amount_cents"] for e in events if e["type"] in CREDIT_TYPES)
    redemptions = sum(e["amount_cents"] for e in events if e["type"] == "REDEMPTION")
    reversals = sum(
        e["amount_cents"] for e in events if e["type"] == "REDEMPTION_REVERSAL"
    )
    redeemed = redemptions - reversals

    from services.money import ratio_two_dp
    ratio = ratio_two_dp(redeemed, loaded) if loaded > 0 else Decimal("0.00")

    window_start = now - timedelta(minutes=policy["redemption_window_minutes"])
    recent = [
        e for e in events
        if e["type"] == "REDEMPTION"
        and e["id"] not in reversed_ids
        and window_start <= e["occurred_at"] <= now
    ]
    merchants = set(
        e["merchant_store_id"] for e in recent
        if e.get("merchant_store_id") not in (None, "")
    )

    held = sum(
        h["amount_cents"] for h in db.holds.values()
        if h["card_id"] == card["id"] and h["state"] == "ACTIVE"
        and h["hold_expires_at"] >= now
    )

    card["current_balance_cents"] = current
    card["held_amount_cents"] = held
    card["available_balance_cents"] = max(0, current - held)
    card["total_loaded_cents"] = loaded
    card["total_redeemed_cents"] = redeemed
    card["drawdown_ratio"] = float(ratio)
    card["_drawdown"] = ratio
    card["distinct_merchant_count"] = len(merchants)
    card["recent_redemption_count"] = len(recent)
    return card


def drawdown(card):
    value = card.get("_drawdown")
    if value is None:
        value = Decimal(str(card.get("drawdown_ratio") or 0))
    return value


def apply_funding_edges(card):
    """The two automatic, mutually inverse ledger-driven edges (PRD 3.4)."""
    balance = card["current_balance_cents"]
    if card["activation_state"] == "ACTIVE" and balance == 0:
        card["activation_state"] = "DEPLETED"
        return True
    if card["activation_state"] == "DEPLETED" and balance > 0:
        card["activation_state"] = "ACTIVE"
        return True
    return False


def escalate_posture(card, target):
    """Automatic escalation only ever raises the rank."""
    if target is None:
        return False
    if POSTURE_RANK[target] > POSTURE_RANK[card["risk_posture"]]:
        card["risk_posture"] = target
        return True
    return False


def posture_target(score, policy, velocity_breach=False):
    if velocity_breach:
        return "RESTRICTED"
    if score >= policy["drain_restrict_score_threshold"]:
        return "RESTRICTED"
    if score >= policy["drain_watch_score_threshold"]:
        return "WATCH"
    return "CLEAR"
