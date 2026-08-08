"""EscalationEvent ladder: the acknowledgement clock and the tier machinery
(PRD 3.8)."""

import calc
import clock
import derived
import store
from store import DB

OPEN_STATES = ("TIER1_OPEN", "TIER2_OPEN", "TIER3_OPEN", "TIER4_OPEN")
ACKED_STATES = ("TIER1_ACKED", "TIER2_ACKED", "TIER3_ACKED", "TIER4_ACKED")


def deadline_for(tier, tier_entered_at_raw, acuity):
    minutes = calc.effective_sla_minutes(tier, acuity)
    return clock.plus_minutes(tier_entered_at_raw, minutes)


def open_escalation(episode, reason, opened_by_user_id):
    entered_at = clock.now_raw()
    return store.make_row("escalations", {
        "episode_id": episode["id"],
        "reason": reason,
        "opened_by_user_id": opened_by_user_id,
        "status": "TIER1_OPEN",
        "current_tier": 1,
        "tier_entered_at": entered_at,
        "ack_deadline_at": deadline_for(1, entered_at, episode["acuity"]),
        "promotion_count": 0,
        "acknowledged_by_user_id": None,
    })


def promote(escalation, episode):
    new_tier = escalation["current_tier"] + 1
    entered_at = clock.now_raw()
    escalation["current_tier"] = new_tier
    escalation["status"] = "TIER%d_OPEN" % new_tier
    escalation["tier_entered_at"] = entered_at
    escalation["ack_deadline_at"] = deadline_for(new_tier, entered_at, episode["acuity"])
    escalation["acknowledged_by_user_id"] = None
    escalation["promotion_count"] = escalation["promotion_count"] + 1
    store.touch(escalation)
    # Promotion INTO TIER3_OPEN additionally moves the owning episode.
    if new_tier == 3 and episode["status"] == "ACTIVE":
        episode["status"] = "ESCALATED"
        store.touch(episode)


def resolve(escalation, episode):
    escalation["status"] = "RESOLVED"
    store.touch(escalation)
    if derived.episode_open_escalation_count(episode["id"]) == 0 and episode["status"] == "ESCALATED":
        episode["status"] = "ACTIVE"
        store.touch(episode)
