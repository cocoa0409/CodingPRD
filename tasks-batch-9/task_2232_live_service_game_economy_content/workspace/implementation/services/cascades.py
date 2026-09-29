"""System cascades: purchase denial, spend-state machine, season conclusion."""
import config
import db
from db import ordered
from response import touch
from services import calc

DENY_OFFER_WITHDRAWN = "OFFER_WITHDRAWN"
DENY_SEASON_CONCLUDED = "SEASON_CONCLUDED"
DENY_SPEND_LOCKED = "SPEND_LOCKED"
DENY_MONITORING = "OFFER_SUSPENDED_BY_MONITORING"


# ---------------------------------------------------------------------------
# PENDING -> DENIED
# ---------------------------------------------------------------------------
def pending_purchases_of_offer(offer):
    rows = [
        p
        for p in db.db.purchases.values()
        if p["offer_id"] == offer["id"] and p["status"] == "PENDING"
    ]
    return ordered(rows)


def pending_purchases_of_player(player):
    rows = [
        p
        for p in db.db.purchases.values()
        if p["player_id"] == player["id"] and p["status"] == "PENDING"
    ]
    return ordered(rows)


def deny_purchase(purchase, reason):
    """The shared PENDING -> DENIED side effects (PRD 3.6)."""
    quoted = purchase["quoted_price_minor"]
    purchase["status"] = "DENIED"
    purchase["deny_reason"] = reason
    touch(purchase)

    offer = db.db.offers.get(purchase["offer_id"])
    if offer is not None:
        offer["pending_purchase_count"] = max(0, offer["pending_purchase_count"] - 1)
        touch(offer)
        season = db.db.seasons.get(offer["season_id"])
        if season is not None:
            season["pending_revenue_minor"] = max(0, season["pending_revenue_minor"] - quoted)
            touch(season)

    player = db.db.players.get(purchase["player_id"])
    if player is not None:
        player["pending_spend_minor"] = max(0, player["pending_spend_minor"] - quoted)
        touch(player)
    return purchase


# ---------------------------------------------------------------------------
# Offer withdrawal / suspension
# ---------------------------------------------------------------------------
def withdraw_offer(offer, reason):
    """LIVE / SUSPENDED / OFFLINE -> WITHDRAWN with the per-origin consequences."""
    previous = offer["availability_status"]
    offer["availability_status"] = "WITHDRAWN"
    touch(offer)
    season = db.db.seasons.get(offer["season_id"])
    if previous == "LIVE" and season is not None:
        season["live_offer_count"] = max(0, season["live_offer_count"] - 1)
        touch(season)
    if previous in ("LIVE", "SUSPENDED"):
        for purchase in pending_purchases_of_offer(offer):
            deny_purchase(purchase, reason)
    return offer


def suspend_offer(offer):
    offer["availability_status"] = "SUSPENDED"
    touch(offer)
    season = db.db.seasons.get(offer["season_id"])
    if season is not None:
        season["live_offer_count"] = max(0, season["live_offer_count"] - 1)
        touch(season)
    return offer


# ---------------------------------------------------------------------------
# Player spend gate
# ---------------------------------------------------------------------------
def accounts_of_player(player):
    rows = [a for a in db.db.accounts.values() if a["player_id"] == player["id"]]
    return ordered(rows)


def lock_player(player):
    player["spend_state"] = "LOCKED"
    for account in accounts_of_player(player):
        account["status"] = "FROZEN"
        touch(account)
    for purchase in pending_purchases_of_player(player):
        deny_purchase(purchase, DENY_SPEND_LOCKED)
    touch(player)
    return player


def unlock_player(player):
    player["spend_state"] = "UNRESTRICTED"
    for account in accounts_of_player(player):
        account["status"] = "ACTIVE"
        touch(account)
    touch(player)
    return player


def reevaluate_spend_state(player, context):
    """Recompute spend_30d_minor then move spend_state per PRD 3.7.

    context is one of SETTLEMENT (may lock), MONITORING (no locking) or
    REFUND (relaxation only).
    """
    player["spend_30d_minor"] = calc.rolling_spend_minor(player)
    spend = player["spend_30d_minor"]
    state = player["spend_state"]
    if context == "SETTLEMENT":
        if spend >= config.SPEND_LOCK_THRESHOLD_MINOR and state != "LOCKED":
            lock_player(player)
            return player
        if state == "UNRESTRICTED" and config.SPEND_COOLDOWN_THRESHOLD_MINOR <= spend:
            player["spend_state"] = "COOLDOWN"
    elif context == "MONITORING":
        if state == "UNRESTRICTED" and (
            config.SPEND_COOLDOWN_THRESHOLD_MINOR
            <= spend
            < config.SPEND_LOCK_THRESHOLD_MINOR
        ):
            player["spend_state"] = "COOLDOWN"
        elif state == "COOLDOWN" and spend < config.SPEND_COOLDOWN_THRESHOLD_MINOR:
            player["spend_state"] = "UNRESTRICTED"
    else:  # REFUND
        if state == "COOLDOWN" and spend < config.SPEND_COOLDOWN_THRESHOLD_MINOR:
            player["spend_state"] = "UNRESTRICTED"
    touch(player)
    return player


# ---------------------------------------------------------------------------
# Season LIVE -> CONCLUDED fan-out (PRD 3.1)
# ---------------------------------------------------------------------------
def conclude_season(season):
    episodes = ordered([e for e in db.db.episodes.values() if e["season_id"] == season["id"]])
    for episode in episodes:
        if episode["status"] == "LIVE":
            episode["status"] = "CONCLUDED"
            touch(episode)

    offers = ordered([o for o in db.db.offers.values() if o["season_id"] == season["id"]])
    withdrawn = [o for o in offers if o["availability_status"] in ("LIVE", "SUSPENDED")]
    for offer in withdrawn:
        offer["availability_status"] = "WITHDRAWN"
        touch(offer)
        for purchase in pending_purchases_of_offer(offer):
            deny_purchase(purchase, DENY_SEASON_CONCLUDED)
    season["live_offer_count"] = 0

    events = ordered([e for e in db.db.live_events.values() if e["season_id"] == season["id"]])
    for event in events:
        if event["status"] == "PLANNED":
            event["status"] = "CANCELLED"
            touch(event)

    season["status"] = "CONCLUDED"
    touch(season)
    return season
