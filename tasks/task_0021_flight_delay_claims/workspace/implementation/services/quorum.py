"""Multi-source flight status quorum and cause classification (PRD §2.7)."""

from __future__ import annotations

from db import db
from services.calculations import QUORUM_WINDOW_MS

# Disruption ordering for tie-break (most-disruptive wins).
DISRUPTION_RANK = {
    "CANCELLED": 0,
    "DIVERTED": 1,
    "RETURNED": 2,
    "LANDED": 3,
    "ON_TIME": 4,
}

# Source priority for cause classification (higher value = higher priority).
SOURCE_PRIORITY = {
    "AVIATION_AUTHORITY": 3,
    "AIRPORT": 2,
    "AIRLINE": 1,
}


def _all_events_for_flight(flight_id: str) -> list[dict]:
    return [e for e in db.flight_status_events.values() if e.get("flight_id") == flight_id]


def evaluate_quorum(flight: dict) -> tuple[str | None, list[dict]]:
    """Return (winning_reported_status, contributing_events) or (None, []).

    A quorum exists for a particular reported status when at least two distinct
    sources within the most-recent QUORUM_WINDOW_MS report it AND at least one
    of those sources is AIRLINE or AVIATION_AUTHORITY.

    Tie-break when two reported_status values both reach quorum:
      - prefer the larger ingested_epoch_ms of the quorum-completing event
      - on equal max, most-disruptive (CANCELLED > DIVERTED > RETURNED > LANDED > ON_TIME)
    """
    events = _all_events_for_flight(flight["id"])
    if not events:
        return None, []

    # Most-recent ingested_epoch_ms in the flight's event log.
    max_ingested = max(e["ingested_epoch_ms"] for e in events)
    window_floor = max_ingested - QUORUM_WINDOW_MS
    window_events = [e for e in events if e["ingested_epoch_ms"] >= window_floor]

    # Group by reported_status
    groups: dict[str, list[dict]] = {}
    for e in window_events:
        groups.setdefault(e["reported_status"], []).append(e)

    candidates: list[tuple[str, list[dict]]] = []
    for status, evs in groups.items():
        sources = {e["source"] for e in evs}
        if len(sources) < 2:
            continue
        if not (sources & {"AIRLINE", "AVIATION_AUTHORITY"}):
            continue
        candidates.append((status, evs))

    if not candidates:
        return None, []

    # Compute the quorum-completing event for each candidate: the event that
    # caused the second distinct (qualifying) source to appear, sorted by
    # ingested_epoch_ms. We approximate by taking max(ingested_epoch_ms) of
    # the contributing events as the tie-break key (this matches the spec
    # phrasing "max ingested_epoch_ms").
    def candidate_key(item):
        status, evs = item
        max_ing = max(e["ingested_epoch_ms"] for e in evs)
        # primary: larger ingested_epoch_ms wins → negate for sort-asc semantics
        # secondary: most-disruptive wins → smaller rank value wins
        return (-max_ing, DISRUPTION_RANK.get(status, 99))

    candidates.sort(key=candidate_key)
    winner_status, winner_events = candidates[0]
    return winner_status, winner_events


def classify_cause(quorum_events: list[dict]) -> str:
    """Pick the mode reported_cause among quorum events (null → OTHER)."""
    if not quorum_events:
        return "OTHER"
    causes = [(e.get("reported_cause") or "OTHER") for e in quorum_events]

    # Tally
    counts: dict[str, int] = {}
    for c in causes:
        counts[c] = counts.get(c, 0) + 1

    max_count = max(counts.values())
    tied = [c for c, n in counts.items() if n == max_count]
    if len(tied) == 1:
        return tied[0]

    # Tie-break by source priority then latest ingested_epoch_ms.
    def cause_key(cause: str):
        # find best (priority, ingested) among events for this cause
        evs = [e for e in quorum_events if (e.get("reported_cause") or "OTHER") == cause]
        best_priority = max(SOURCE_PRIORITY.get(e["source"], 0) for e in evs)
        best_ing = max(e["ingested_epoch_ms"] for e in evs if SOURCE_PRIORITY.get(e["source"], 0) == best_priority)
        # higher priority wins → negate; later ingested wins → negate
        return (-best_priority, -best_ing)

    tied.sort(key=cause_key)
    return tied[0]
