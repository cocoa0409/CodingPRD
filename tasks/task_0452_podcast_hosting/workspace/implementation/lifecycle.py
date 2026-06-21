"""Cross-entity cascades and shared state-transition side effects.

These helpers mutate placement / episode / campaign statuses and then reconcile
all affected derived fields exactly once per request, so each touched entity gets
exactly one version bump / updated_at refresh (PRD §2.6).
"""

import db
from common import touch
import recompute


def _campaigns_touched(campaign_ids):
    for cid in campaign_ids:
        c = db.db.ad_campaigns.get(cid)
        if c is not None:
            recompute.recompute_campaign_ledger(c)


def _episodes_touched(episode_ids):
    for eid in episode_ids:
        e = db.db.episodes.get(eid)
        if e is not None:
            recompute.recompute_episode_fill(e)


def cancel_placements_for_episode(episode, terminal_status):
    """Move every {PROPOSED, INSERTED} placement on an episode to terminal_status.

    Used by the show-suspend (L2) and episode-unpublish cascades (terminal
    CANCELLED). Each placement releases its reserve and the episode fill metrics
    + campaign ledgers are recomputed. Returns the set of affected campaign ids.
    """
    affected_campaigns = set()
    for p in db.db.ad_placements.values():
        if p["episode_id"] == episode["id"] and p["status"] in ("PROPOSED", "INSERTED"):
            p["status"] = terminal_status
            touch(p)
            affected_campaigns.add(p["campaign_id"])
    return affected_campaigns


def suspend_show_cascade(show):
    """Show ACTIVE -> SUSPENDED three-level cascade (PRD §2.6 / §3.1).

    L1: every PUBLISHED episode -> UNPUBLISHED.
    L2: on each such episode, every PROPOSED/INSERTED placement -> CANCELLED.
    L3: each cancelled placement releases its reserve; campaign ledgers and
        episode fill metrics recomputed.
    """
    affected_campaigns = set()
    affected_episodes = []
    for e in db.db.episodes.values():
        if e["show_id"] == show["id"] and e["publish_status"] == "PUBLISHED":
            e["publish_status"] = "UNPUBLISHED"
            touch(e)
            affected_episodes.append(e)
            affected_campaigns |= cancel_placements_for_episode(e, "CANCELLED")
    # Reconcile derived fields once each.
    _episodes_touched([e["id"] for e in affected_episodes])
    _campaigns_touched(affected_campaigns)


def unpublish_episode_cascade(episode):
    """Episode PUBLISHED -> UNPUBLISHED cascade (PRD §3.2).

    Cancel its PROPOSED/INSERTED placements, release reserves, recompute fill.
    Caller is responsible for setting publish_status and touching the episode.
    """
    affected_campaigns = cancel_placements_for_episode(episode, "CANCELLED")
    recompute.recompute_episode_fill(episode)
    _campaigns_touched(affected_campaigns)


def archive_show_disable_feeds(show):
    """Archiving a show disables all of its feeds (PRD §3.1, §3.3)."""
    for f in db.db.feeds.values():
        if f["show_id"] == show["id"] and f["status"] != "DISABLED":
            f["status"] = "DISABLED"
            touch(f)


def reject_proposed_placements(campaign):
    """Campaign pause / exhaustion cascade L1 (PRD §3.4, §3.6).

    Every PROPOSED placement of the campaign -> REJECTED, releasing its reserve;
    campaign ledger + affected episode fill metrics recomputed. INSERTED
    placements are left intact.
    """
    affected_episodes = set()
    for p in db.db.ad_placements.values():
        if p["campaign_id"] == campaign["id"] and p["status"] == "PROPOSED":
            p["status"] = "REJECTED"
            touch(p)
            affected_episodes.add(p["episode_id"])
    _episodes_touched(affected_episodes)
    recompute.recompute_campaign_ledger(campaign)
