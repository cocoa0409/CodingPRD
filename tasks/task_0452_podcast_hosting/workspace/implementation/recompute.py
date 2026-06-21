"""Synchronous derived-field reconciliation and cascades (PRD §2.6).

The platform never defers reconciliation: derived fields are correct the instant
the mutating request returns. Each entity touched by a cascade gets its own
updated_at refreshed and version bumped (common.touch).
"""

import calc
import db
from common import touch


# ---------------------------------------------------------------------------
# Show.episode_count — count of episodes whose publish_status != DELETED
# (PRD §3.1). Recompute is itself a mutation -> touch the show.
# ---------------------------------------------------------------------------

def recompute_show_episode_count(show):
    count = 0
    for e in db.db.episodes.values():
        if e["show_id"] == show["id"] and e["publish_status"] != "DELETED":
            count += 1
    if show["episode_count"] != count:
        show["episode_count"] = count
        touch(show)
    else:
        show["episode_count"] = count


# ---------------------------------------------------------------------------
# Episode fill metrics — filled_slots / available_slots / fill_rate (PRD §3.2).
# Recompute is a mutation -> touch the episode.
# ---------------------------------------------------------------------------

def recompute_episode_fill(episode):
    filled, available, rate = calc.fill_metrics(episode)
    changed = (episode["filled_slots"] != filled or
               episode["available_slots"] != available or
               episode["fill_rate"] != rate)
    episode["filled_slots"] = filled
    episode["available_slots"] = available
    episode["fill_rate"] = rate
    if changed:
        touch(episode)


# ---------------------------------------------------------------------------
# Campaign budget ledger — reserved / spent / available (PRD §3.4).
# Recompute is a mutation -> touch the campaign (which also advances its
# version, the OCC counter for placement booking).
# ---------------------------------------------------------------------------

def recompute_campaign_ledger(campaign):
    reserved, spent, available = calc.campaign_ledger(campaign)
    changed = (campaign["reserved_budget_cents"] != reserved or
               campaign["spent_budget_cents"] != spent or
               campaign["available_budget_cents"] != available)
    campaign["reserved_budget_cents"] = reserved
    campaign["spent_budget_cents"] = spent
    campaign["available_budget_cents"] = available
    if changed:
        touch(campaign)
