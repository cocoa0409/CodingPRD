"""Escalation ladder: target selection, paging fan-out, climbing/wrapping.

PRD 3.3 (selector + fan-out) and 3.4 (climbing/wrapping the cyclic ladder).
"""
from db import db, new_id, next_seq
from errors import ApiError

# Fixed channel-priority order for the fan-out (PRD 3.3):
#   voice first, then SMS, then push, then email (always).
CHANNEL_ORDER = [
    ("voice_number", "VOICE"),
    ("sms_number", "SMS"),
    ("push_token", "PUSH"),
]


def tiers_for_policy(policy_id):
    """All tiers of a policy, ordered by tier_level ascending."""
    tiers = [t for t in db.tiers.values() if t["policy_id"] == policy_id]
    tiers.sort(key=lambda t: t["tier_level"])
    return tiers


def select_target_responder(schedule_id):
    """escalation_target_selector (PRD 3.3).

    Candidate set: shifts on schedule covering now via half-open
    [starts_at, ends_at). Rank by starts_at ASC, tie-break created_at ASC.
    First candidate's responder_id is the target. Empty -> None.
    """
    now = db.clock.now()
    candidates = []
    for sh in db.shifts.values():
        if sh["schedule_id"] != schedule_id:
            continue
        if sh["starts_at"] <= now < sh["ends_at"]:
            candidates.append(sh)
    if not candidates:
        return None
    candidates.sort(key=lambda s: (s["starts_at"], s["created_at"]))
    return candidates[0]["responder_id"]


def enabled_channels(responder):
    """Ordered list of (channel) for enabled channels; EMAIL always last."""
    channels = []
    for field, channel in CHANNEL_ORDER:
        if responder.get(field):
            channels.append(channel)
    channels.append("EMAIL")
    return channels


def create_page_attempts(incident, responder_id, tier_level, round_index):
    """calc paging_fanout: one PageAttempt per enabled channel."""
    responder = db.responders[responder_id]
    now = db.clock.now()
    for channel in enabled_channels(responder):
        pa_id = new_id()
        db.page_attempts[pa_id] = {
            "id": pa_id,
            "created_at": now,
            "_seq": next_seq(),
            "incident_id": incident["id"],
            "responder_id": responder_id,
            "tier_level": tier_level,
            "channel": channel,
            "round_index": round_index,
        }


def _resolve_step(incident, target_tier_index, round_index):
    """Resolve the (tier_index, round_index) to a (tier, responder_id).

    target_tier_index is 0-based into the ordered tier list. Returns
    (tier_record, responder_id) or raises ERR_NO_ESCALATION_TARGET.
    """
    tiers = tiers_for_policy(incident["policy_id"])
    if not tiers:
        raise ApiError("ERR_NO_ESCALATION_TARGET", "Policy has no escalation tiers.")
    tier = tiers[target_tier_index]
    responder_id = select_target_responder(tier["schedule_id"])
    if responder_id is None:
        raise ApiError(
            "ERR_NO_ESCALATION_TARGET",
            "No on-call responder currently covers the tier's schedule.",
        )
    return tier, responder_id


def first_page(incident):
    """Automatic first page at trigger (PRD 3.2): advance PENDING -> ESCALATING,
    current_tier_level -> tier 1, create PageAttempts for tier-1 responder.

    Raises ERR_NO_ESCALATION_TARGET if no tiers or no covering shift.
    """
    tiers = tiers_for_policy(incident["policy_id"])
    if not tiers:
        raise ApiError("ERR_NO_ESCALATION_TARGET", "Policy has no escalation tiers.")
    tier, responder_id = _resolve_step(incident, 0, 0)
    incident["current_tier_level"] = tier["tier_level"]
    incident["escalation_status"] = "ESCALATING"
    incident["_round_index"] = 0
    incident["_tier_index"] = 0
    create_page_attempts(incident, responder_id, tier["tier_level"], 0)


def manual_escalate(incident):
    """POST /incidents/{id}/escalate (PRD 3.4) — advance one rung.

    Returns nothing; mutates incident in place. The OCC + state checks are
    performed by the caller before invoking this. Determines the next tier
    within tiers, wrapping to tier 1 and advancing round_index while repeat
    rounds remain. If no next tier/round remains -> escalation_status
    EXHAUSTED and no page. Reachable-target failures raise
    ERR_NO_ESCALATION_TARGET (no state change, no page).
    """
    tiers = tiers_for_policy(incident["policy_id"])
    if not tiers:
        raise ApiError("ERR_NO_ESCALATION_TARGET", "Policy has no escalation tiers.")

    cur_index = incident.get("_tier_index", 0)
    cur_round = incident.get("_round_index", 0)
    repeat_rounds = db.policies[incident["policy_id"]]["repeat_rounds"]

    next_index = cur_index + 1
    next_round = cur_round
    if next_index >= len(tiers):
        # wrap: would move to the next repeat round at tier 1
        next_round = cur_round + 1
        next_index = 0
        # round_index ranges 0..repeat_rounds; a round beyond repeat_rounds
        # has no further tier/round to page.
        if next_round > repeat_rounds:
            incident["escalation_status"] = "EXHAUSTED"
            return

    tier, responder_id = _resolve_step(incident, next_index, next_round)
    incident["_tier_index"] = next_index
    incident["_round_index"] = next_round
    incident["current_tier_level"] = tier["tier_level"]
    incident["escalation_status"] = "ESCALATING"
    create_page_attempts(incident, responder_id, tier["tier_level"], next_round)
