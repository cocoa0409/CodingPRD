"""Client budget conservation + derived-field reconciliation (PRD §2.6, §2.8, §1.3).

These functions recompute Client.* computed fields from the underlying rows.
They are pure recomputations: they do NOT bump the client's version/updated_at on
their own. The caller decides whether the client row was "mutated" for OCC/touch
purposes (only boost reserve bumps version, per PRD §2.7).
"""
import db


def client_boost_campaigns(client_id):
    return [b for b in db.boost_campaigns.values() if b["client_id"] == client_id]


def recompute_client_budget(client):
    """boost_reserved_cents / boost_spent_cents / boost_available_cents (§2.6).

    boost_reserved_cents = sum reserved_budget_cents over RESERVED|RUNNING
    boost_spent_cents     = sum spent_budget_cents over RUNNING|COMPLETED
    boost_available_cents = max(0, limit - reserved - spent)
    """
    cid = client["id"]
    reserved = sum(
        b["reserved_budget_cents"]
        for b in client_boost_campaigns(cid)
        if b["status"] in ("RESERVED", "RUNNING")
    )
    spent = sum(
        b["spent_budget_cents"]
        for b in client_boost_campaigns(cid)
        if b["status"] in ("RUNNING", "COMPLETED")
    )
    client["boost_reserved_cents"] = reserved
    client["boost_spent_cents"] = spent
    available = client["boost_budget_limit_cents"] - reserved - spent
    client["boost_available_cents"] = available if available > 0 else 0


def count_posts_published_this_cycle(client):
    """posts_published_this_cycle: PUBLISHED items whose published_cycle_index ==
    the client's current_cycle_index (§2.8)."""
    cid = client["id"]
    cur = client["current_cycle_index"]
    return sum(
        1
        for ci in db.content_items.values()
        if ci["client_id"] == cid
        and ci["status"] == "PUBLISHED"
        and ci.get("published_cycle_index") == cur
    )


def count_open_conversations(client):
    """open_conversation_count: conversations on this client's channels with
    status == OPEN (§2.8)."""
    cid = client["id"]
    channel_ids = {ch["id"] for ch in db.channels.values() if ch["client_id"] == cid}
    return sum(
        1
        for conv in db.conversations.values()
        if conv["channel_id"] in channel_ids and conv["status"] == "OPEN"
    )


def recompute_client_derived(client):
    """Refresh all read-derived computed counters on a client."""
    recompute_client_budget(client)
    client["posts_published_this_cycle"] = count_posts_published_this_cycle(client)
    client["open_conversation_count"] = count_open_conversations(client)
