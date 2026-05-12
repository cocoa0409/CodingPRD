"""Cross-entity cascade: when a Disposal or Violation is retrospectively
changed, any RankingPeriod whose window contains the affected timestamp
gets invalidated (per PRD §2.8).

- OPEN periods: clear leaderboard to [] (versioned bump)
- CLOSED periods (published_at is null): clear leaderboard and revert status -> OPEN
- PUBLISHED periods: NOT touched (immutable in this version)
"""

from __future__ import annotations

import datetime as dt

from db import db
from services.common import parse_iso8601_utc


def invalidate_periods_overlapping(
    *,
    community_id: str,
    affected_time_utc: dt.datetime,
) -> None:
    for p in db.ranking_periods.values():
        if p["community_id"] != community_id:
            continue
        if p["status"] == "PUBLISHED":
            continue
        ws = parse_iso8601_utc(p["window_start"])
        we = parse_iso8601_utc(p["window_end"])
        if not (ws <= affected_time_utc < we):
            continue

        mutated = False
        if p["status"] == "CLOSED" and p.get("published_at") is None:
            p["status"] = "OPEN"
            p["leaderboard"] = []
            mutated = True
        elif p["status"] == "OPEN":
            if p.get("leaderboard"):
                p["leaderboard"] = []
                mutated = True
        if mutated:
            db.stamp_update(p)
