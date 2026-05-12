"""Card validity & expiration helpers."""
import db
from clock import now, parse_iso


def is_card_valid_now(card: dict) -> bool:
    """Card is within [valid_from, valid_until] AND status not EXPIRED."""
    if card.get("status") == "EXPIRED":
        return False
    n = now()
    try:
        vfrom = parse_iso(card["valid_from"])
        vuntil = parse_iso(card["valid_until"])
    except Exception:
        return False
    return vfrom <= n <= vuntil


def expire_card_if_due(card: dict) -> bool:
    """If card.valid_until < now and status not already EXPIRED, expire it.

    Side effects (per state machine):
      - status -> EXPIRED
      - bound_vehicle_ids cleared
      - auto_pay_enabled forced to false
      - version & updated_at bumped
    Returns True if a transition happened.
    """
    if card.get("status") == "EXPIRED":
        return False
    try:
        vuntil = parse_iso(card["valid_until"])
    except Exception:
        return False
    if now() <= vuntil:
        return False
    card["status"] = "EXPIRED"
    card["bound_vehicle_ids"] = []
    card["auto_pay_enabled"] = False
    db.stamp_update(card)
    return True


def expire_all_due_cards() -> int:
    """Expire every card past its valid_until. Returns count expired."""
    n = 0
    for c in list(db.cards.values()):
        if expire_card_if_due(c):
            n += 1
    return n
