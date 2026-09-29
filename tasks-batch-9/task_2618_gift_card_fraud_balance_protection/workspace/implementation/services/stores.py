"""Rack tamper classification, store floor posture and the three-hop
rack-tamper cascade (PRD 3.1)."""
import clock
import db as dbm
from db import db

FLOOR_POSTURES = ("OPEN", "HEIGHTENED", "SUSPENDED")
TAMPER_STATES = ("INTACT", "SUSPECT", "TAMPERED")


def classify_rack(missing_card_count, seal_breaks_observed, policy):
    """First match wins (PRD 3.1)."""
    if (missing_card_count >= policy["rack_shrink_threshold"]
            or seal_breaks_observed >= policy["rack_seal_break_threshold"]):
        return "TAMPERED"
    if missing_card_count >= 1 or seal_breaks_observed >= 1:
        return "SUSPECT"
    return "INTACT"


def store_racks(store_id):
    return [r for r in db.racks.values() if r["store_id"] == store_id]


def open_alerts_for_store(store_id):
    out = []
    for alert in db.alerts.values():
        if alert["state"] not in ("OPEN", "TRIAGED"):
            continue
        card = db.cards.get(alert["card_id"])
        if card is not None and card.get("store_id") == store_id:
            out.append(alert)
    return out


def recompute_store(store):
    """Derive the three counters and the floor posture. Pure recomputation."""
    policy = dbm.policy()
    racks = store_racks(store["id"])
    tampered = len([r for r in racks if r["tamper_state"] == "TAMPERED"])
    suspect = len([r for r in racks if r["tamper_state"] == "SUSPECT"])
    open_alerts = len(open_alerts_for_store(store["id"]))
    store["tampered_rack_count"] = tampered
    store["suspect_rack_count"] = suspect
    store["open_alert_count"] = open_alerts
    if tampered >= 1:
        store["floor_posture"] = "SUSPENDED"
    elif suspect >= 1 or open_alerts >= policy["floor_heightened_alert_threshold"]:
        store["floor_posture"] = "HEIGHTENED"
    else:
        store["floor_posture"] = "OPEN"
    return store


def touch_store(store):
    """Recompute the derived counters and bump the store's version."""
    if store is None:
        return None
    recompute_store(store)
    dbm.touch(store)
    return store


def touch_store_for_card(card):
    """Recompute the store behind a card, when the card has one (DIGITAL
    cards carry no store, so nothing is touched)."""
    if card is None or not card.get("store_id"):
        return None
    store = db.stores.get(card["store_id"])
    if store is None:
        return None
    return touch_store(store)


def void_inactive_cards(store):
    """HOP 3 of the rack-tamper cascade: every INACTIVE card belonging to the
    suspended store is voided and frozen, in created_at ASC order. ACTIVE,
    DEPLETED and CLOSED cards are untouched, and remediation never un-voids."""
    victims = dbm.by_created([
        c for c in db.cards.values()
        if c.get("store_id") == store["id"] and c["activation_state"] == "INACTIVE"
    ])
    for card in victims:
        card["activation_state"] = "VOIDED"
        card["risk_posture"] = "FROZEN"
        card["closed_at"] = clock.now()
        dbm.touch(card)
    return victims
