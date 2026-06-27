"""Weekly activity streaks (PRD §3.8 / streak_bonus_computation).

A week is the Mon-Sun UTC period; week_index = floor((days since 1970-01-05) / 7).
current_streak_weeks = count of consecutive week indexes (ending at the latest
qualifying week) in which the member had >= 1 claim reach AVAILABLE.

The streak is recomputed whenever one of the member's claims matures
PENDING -> AVAILABLE.
"""
from clock import parse_iso
from constants import WEEK_EPOCH_ISO
from db import base_common_fields, touch
from services.calculations import compute_streak_bonus

_WEEK_EPOCH = parse_iso(WEEK_EPOCH_ISO)


def week_index_of(dt):
    """Week index = floor((days since 1970-01-05 Monday) / 7)."""
    delta = dt - _WEEK_EPOCH
    days = delta.days  # floor of whole days for non-negative deltas
    # For negative deltas (before epoch) delta.days already floors toward -inf.
    return days // 7


def _get_or_create_streak(store, member_id):
    sid = store.bonus_streak_by_member.get(member_id)
    if sid is not None:
        return store.bonus_streaks[sid]
    streak = base_common_fields(store, full=True)
    streak.update({
        "member_id": member_id,
        "current_streak_weeks": 0,
        "longest_streak_weeks": 0,
        "last_activity_week_index": None,
        "pending_streak_bonus_cents": 0,
    })
    store.bonus_streaks[streak["id"]] = streak
    store.bonus_streak_by_member[member_id] = streak["id"]
    return streak


def _qualifying_week_indexes(store, member_id):
    """Set of week indexes in which the member had >= 1 claim reach AVAILABLE.

    Once a claim reaches AVAILABLE it has 'reached AVAILABLE' for streak purposes
    even if it later moves on (RESERVED/PAID); a claim that never matured
    (still PENDING) or was clawed/expired-before-available does not count. We use
    the claim's matured_week_index, recorded when it matures, as the activity week.
    """
    weeks = set()
    for c in store.reward_claims.values():
        if c["member_id"] != member_id:
            continue
        wk = c.get("_matured_week_index")
        if wk is not None:
            weeks.add(wk)
    return weeks


def recompute_streak(store, member_id):
    """Recompute a member's BonusStreak from the set of qualifying weeks."""
    streak = _get_or_create_streak(store, member_id)
    weeks = _qualifying_week_indexes(store, member_id)
    if not weeks:
        changed = (
            streak["current_streak_weeks"] != 0
            or streak["pending_streak_bonus_cents"] != 0
            or streak["last_activity_week_index"] is not None
        )
        streak["current_streak_weeks"] = 0
        streak["pending_streak_bonus_cents"] = 0
        streak["last_activity_week_index"] = None
        if changed:
            touch(store, streak)
        return streak

    latest = max(weeks)
    # Count consecutive weeks ending at `latest`.
    count = 0
    w = latest
    while w in weeks:
        count += 1
        w -= 1

    streak["current_streak_weeks"] = count
    streak["last_activity_week_index"] = latest
    if count > streak["longest_streak_weeks"]:
        streak["longest_streak_weeks"] = count
    streak["pending_streak_bonus_cents"] = compute_streak_bonus(count)
    touch(store, streak)
    return streak
