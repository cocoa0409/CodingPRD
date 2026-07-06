"""Retainer waterfall reconciliation (PRD §3.8 / calc retainer_reconciliation).

Two variants differing only in eligibility:
  provisional (GET projection): episodes SCHEDULED or PUBLISHED; a SCHEDULED
    episode is counted by intended publish window — published_at when set, else
    treated as in-window. Over-counts vs final.
  final (POST close): only PUBLISHED with non-null published_at inside the window.
"""
from constants import OVERAGE_RATE_CENTS as _OVERAGE_RATE_CENTS
from db import db


def _in_window(dt, start, end):
    """Half-open [start, end): start <= dt < end."""
    return dt is not None and start <= dt < end


def _eligible_episodes(contract, cycle, variant):
    show_id = contract["show_id"]
    start = cycle["cycle_start_utc"]
    end = cycle["cycle_end_utc"]
    episodes = [e for e in db.episodes.all() if e["show_id"] == show_id]
    result = []
    if variant == "final":
        for e in episodes:
            if e["status"] == "PUBLISHED" and _in_window(e["published_at"], start, end):
                result.append(e)
    else:  # provisional
        for e in episodes:
            if e["status"] == "PUBLISHED":
                if _in_window(e["published_at"], start, end):
                    result.append(e)
            elif e["status"] == "SCHEDULED":
                # counted by intended publish window: published_at when set, else
                # treated as in-window.
                if e["published_at"] is None or _in_window(e["published_at"], start, end):
                    result.append(e)
    return result


def reconcile(contract, cycle, variant):
    """Return (included_consumed, overage_episode_count, overage_subtotal_cents)."""
    eligible = _eligible_episodes(contract, cycle, variant)
    eligible.sort(key=lambda e: (
        e["published_at"] if e["published_at"] is not None else e["created_at"],
        e["created_at"],
        e["_seq"],
    ))
    included = contract["monthly_included_episodes"]
    count = len(eligible)
    included_consumed = min(count, included)
    overage = max(0, count - included)
    overage_subtotal = overage * _OVERAGE_RATE_CENTS[contract["tier"]]
    return included_consumed, overage, overage_subtotal
