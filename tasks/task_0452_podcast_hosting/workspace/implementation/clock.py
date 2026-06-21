"""Logical clock advance and the due time-driven transitions (PRD §2.9, §3.2, §3.3).

Setting the clock fires every transition that has become due:
  - each SCHEDULED episode with scheduled_publish_at <= clock, whose show is
    ACTIVE and whose media is READY, auto-publishes (recomputes show episode_count);
  - each ACTIVE subscription past its period_end -> PAST_DUE;
  - each PAST_DUE subscription past period_end + GRACE_MS -> CANCELLED
    (clearing access_token).
Lapses are processed before grace cancellations so a far clock jump moves an
ACTIVE subscription ACTIVE -> PAST_DUE -> CANCELLED in one advance.
"""

import db
from common import touch
import recompute
from timeutil import parse_iso, add_ms


def set_clock(to_iso8601):
    db.db.clock = to_iso8601
    clock_dt = parse_iso(to_iso8601)
    _fire_due_episode_publishes(clock_dt)
    _fire_due_subscription_transitions(clock_dt)


def _fire_due_episode_publishes(clock_dt):
    affected_shows = set()
    for e in db.db.episodes.values():
        if e["publish_status"] != "SCHEDULED":
            continue
        sched = e.get("scheduled_publish_at")
        if sched is None:
            continue
        if parse_iso(sched) > clock_dt:
            continue
        show = db.db.shows.get(e["show_id"])
        if show is None or show["status"] != "ACTIVE":
            continue
        if e["media_status"] != "READY":
            continue
        e["publish_status"] = "PUBLISHED"
        touch(e)
        affected_shows.add(show["id"])
    for sid in affected_shows:
        show = db.db.shows.get(sid)
        if show is not None:
            recompute.recompute_show_episode_count(show)


def _fire_due_subscription_transitions(clock_dt):
    # Pass 1: ACTIVE -> PAST_DUE when the clock has passed period_end.
    for s in db.db.subscriptions.values():
        if s["status"] != "ACTIVE":
            continue
        period_end = parse_iso(s["period_end"])
        if clock_dt > period_end:
            s["status"] = "PAST_DUE"
            touch(s)
    # Pass 2: PAST_DUE -> CANCELLED once the clock passes period_end + GRACE_MS.
    for s in db.db.subscriptions.values():
        if s["status"] != "PAST_DUE":
            continue
        period_end = parse_iso(s["period_end"])
        if clock_dt > add_ms(period_end, db.GRACE_MS):
            s["status"] = "CANCELLED"
            s["access_token"] = None
            touch(s)
