"""Waitlist ordering (scaffold §1.3 waitlist_ordering / PRD §3.3).

Candidate set = PENDING entries with the same community_id + target_care_level.
Sort ascending by:
  1. enqueued_period_index ASC   (earlier period wins — primary)
  2. priority_score DESC         (higher priority wins ties on period)
  3. created_at ASC              (earliest enqueue breaks remaining ties; via _seq)
rank = 1-based index. id is NEVER used as a tie-break.
"""
from __future__ import annotations

from typing import Dict, List

import db


def _queue(community_id: str, target_care_level: str) -> List[Dict]:
    candidates = [
        w
        for w in db.waitlist_entries.values()
        if w["status"] == "PENDING"
        and w["community_id"] == community_id
        and w["target_care_level"] == target_care_level
    ]
    candidates.sort(
        key=lambda w: (
            w["enqueued_period_index"],
            -w["priority_score"],
            w["_seq"],
        )
    )
    return candidates


def recompute_ranks(community_id: str, target_care_level: str) -> None:
    """Reassign 1-based rank to every PENDING entry in the queue.

    Recomputed on every create / place / withdraw, so a PENDING entry's stored
    `rank` is always current; offer/place enforce head-of-queue via `rank == 1`.
    """
    for idx, w in enumerate(_queue(community_id, target_care_level), start=1):
        w["rank"] = idx
