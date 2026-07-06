"""Existence lookups that raise the correct not-found error (PRD §2.5, priority 3/4)."""
import db
from errors import (
    err, ERR_CLIENT_NOT_FOUND, ERR_PACKAGE_NOT_FOUND, ERR_CHANNEL_NOT_FOUND,
    ERR_CONTENT_NOT_FOUND, ERR_SLOT_NOT_FOUND, ERR_BOOST_NOT_FOUND,
    ERR_CONVERSATION_NOT_FOUND, ERR_COLLAB_NOT_FOUND, ERR_ASSET_NOT_FOUND,
    ERR_MESSAGE_NOT_FOUND, ERR_TARGET_NOT_FOUND, ERR_SNAPSHOT_NOT_FOUND,
    ERR_LEDGER_NOT_FOUND,
)


def get_client(cid):
    c = db.clients.get(cid)
    if c is None:
        raise err(ERR_CLIENT_NOT_FOUND, "Client %s not found" % cid)
    return c


def get_package(pid):
    p = db.retainer_packages.get(pid)
    if p is None:
        raise err(ERR_PACKAGE_NOT_FOUND, "RetainerPackage %s not found" % pid)
    return p


def get_channel(chid):
    ch = db.channels.get(chid)
    if ch is None:
        raise err(ERR_CHANNEL_NOT_FOUND, "Channel %s not found" % chid)
    return ch


def get_content(ciid):
    ci = db.content_items.get(ciid)
    if ci is None:
        raise err(ERR_CONTENT_NOT_FOUND, "ContentItem %s not found" % ciid)
    return ci


def get_slot(sid):
    s = db.schedule_slots.get(sid)
    if s is None:
        raise err(ERR_SLOT_NOT_FOUND, "ScheduleSlot %s not found" % sid)
    return s


def get_boost(bid):
    b = db.boost_campaigns.get(bid)
    if b is None:
        raise err(ERR_BOOST_NOT_FOUND, "BoostCampaign %s not found" % bid)
    return b


def get_conversation(cid):
    c = db.conversations.get(cid)
    if c is None:
        raise err(ERR_CONVERSATION_NOT_FOUND, "Conversation %s not found" % cid)
    return c


def get_collab(cid):
    c = db.influencer_collabs.get(cid)
    if c is None:
        raise err(ERR_COLLAB_NOT_FOUND, "InfluencerCollab %s not found" % cid)
    return c


def get_asset(aid):
    a = db.ugc_assets.get(aid)
    if a is None:
        raise err(ERR_ASSET_NOT_FOUND, "UGCAsset %s not found" % aid)
    return a


def get_message(mid):
    m = db.messages.get(mid)
    if m is None:
        raise err(ERR_MESSAGE_NOT_FOUND, "EngagementMessage %s not found" % mid)
    return m


def get_target(tid):
    t = db.content_targets.get(tid)
    if t is None:
        raise err(ERR_TARGET_NOT_FOUND, "ContentTarget %s not found" % tid)
    return t


def get_snapshot(sid):
    s = db.analytics_snapshots.get(sid)
    if s is None:
        raise err(ERR_SNAPSHOT_NOT_FOUND, "AnalyticsSnapshot %s not found" % sid)
    return s


def get_ledger(lid):
    l = db.ledger_entries.get(lid)
    if l is None:
        raise err(ERR_LEDGER_NOT_FOUND, "LedgerEntry %s not found" % lid)
    return l


def active_package_for_client(client_id):
    for p in db.retainer_packages.values():
        if p["client_id"] == client_id and p["status"] == "ACTIVE":
            return p
    return None
