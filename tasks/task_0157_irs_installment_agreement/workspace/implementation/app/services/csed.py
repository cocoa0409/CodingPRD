"""CSED computation, tolling event lifecycle.

Implements §1.3 calc csed_calculation:
- csed_base_date = assessment_date + 10 years
- Merge tolling intervals with half-open semantics [start, end)
- csed_effective_date = csed_base_date + total_tolling_seconds
"""
from __future__ import annotations

from datetime import timedelta
from typing import List, Optional

from app.errors import ERR_OVERLAPPING_TOLLING, raise_error
from app.services.common import bump_version, init_common_fields
from app.store import STORE, new_id
from app.timeutil import CLOCK, add_years, fmt, now_iso, parse_iso


# ---------------------------------------------------------------------------
# Tolling event CRUD
# ---------------------------------------------------------------------------

def _events_for(liability_id: str) -> list:
    return [e for e in STORE.tolling_events.values() if e["liability_id"] == liability_id]


def _open_event_of_kind(liability_id: str, event_kind: str) -> Optional[dict]:
    for e in _events_for(liability_id):
        if e["event_kind"] == event_kind and e.get("end_date") is None:
            return e
    return None


def open_event(liability_id: str, event_kind: str, *, source_ref: Optional[str] = None,
               start_iso: Optional[str] = None) -> dict:
    """Open a new tolling event of the given kind on a liability.

    Rejects (ERR_OVERLAPPING_TOLLING) when:
      - another open event of the same kind exists for this liability
      - the new closed interval would overlap an existing event on this liability
    """
    start = start_iso or now_iso()
    start_dt = parse_iso(start)

    # Check forbidden simultaneous-open of same kind
    if _open_event_of_kind(liability_id, event_kind) is not None:
        raise_error(
            ERR_OVERLAPPING_TOLLING,
            f"A {event_kind} tolling event is already open for this liability.",
        )

    evt = {
        "id": new_id(),
        "liability_id": liability_id,
        "event_kind": event_kind,
        "start_date": fmt(start_dt),
        "end_date": None,
        "source_ref": source_ref,
    }
    init_common_fields(evt, with_version=False)
    STORE.tolling_events[evt["id"]] = evt
    recompute_csed(liability_id)
    return evt


def close_events_of_kind(liability_id: str, event_kind: str, *, end_iso: Optional[str] = None) -> List[dict]:
    """Close all currently-open events of the given kind for a liability."""
    end = end_iso or now_iso()
    closed: List[dict] = []
    for e in _events_for(liability_id):
        if e["event_kind"] == event_kind and e.get("end_date") is None:
            e["end_date"] = end
            closed.append(e)
    if closed:
        recompute_csed(liability_id)
    return closed


# ---------------------------------------------------------------------------
# CSED recomputation
# ---------------------------------------------------------------------------

def _merged_tolling_duration_seconds(liability_id: str) -> float:
    events = _events_for(liability_id)
    if not events:
        return 0.0

    now_dt = CLOCK.now()
    intervals = []
    for e in events:
        start = parse_iso(e["start_date"])
        if e.get("end_date"):
            end = parse_iso(e["end_date"])
        else:
            end = now_dt
        if end < start:
            end = start
        intervals.append((start, end))

    intervals.sort(key=lambda i: (i[0], i[1]))

    # Merge with half-open semantics: next.start <= current.end means overlap/merge.
    merged = []
    cur_s, cur_e = intervals[0]
    for s, e in intervals[1:]:
        if s <= cur_e:
            if e > cur_e:
                cur_e = e
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e
    merged.append((cur_s, cur_e))

    total = 0.0
    for s, e in merged:
        total += (e - s).total_seconds()
    return total


def recompute_csed(liability_id: str) -> None:
    """Recompute csed_effective_date for a liability based on its tolling events."""
    liab = STORE.tax_liabilities.get(liability_id)
    if liab is None:
        return
    base_dt = parse_iso(liab["csed_base_date"])
    total_tolling = _merged_tolling_duration_seconds(liability_id)
    new_dt = base_dt + timedelta(seconds=total_tolling)
    new_str = fmt(new_dt)
    if liab.get("csed_effective_date") != new_str:
        liab["csed_effective_date"] = new_str
        bump_version(liab)


def recompute_csed_for_read(liability_id: str) -> Optional[str]:
    """Return the drift-adjusted csed_effective_date as of CLOCK.now()
    without mutating storage. Per PRD §3.3: while at least one tolling
    event remains open, the effective expiration drifts forward as
    wall-clock time advances.

    Returns the ISO string, or None if the liability does not exist.
    """
    liab = STORE.tax_liabilities.get(liability_id)
    if liab is None:
        return None
    base_dt = parse_iso(liab["csed_base_date"])
    total_tolling = _merged_tolling_duration_seconds(liability_id)
    new_dt = base_dt + timedelta(seconds=total_tolling)
    return fmt(new_dt)


def init_csed_for_new_liability(liab: dict) -> None:
    """Set csed_base_date = assessment_date + 10 years; csed_effective_date := csed_base_date."""
    assessment_dt = parse_iso(liab["assessment_date"])
    base_dt = add_years(assessment_dt, 10)
    liab["csed_base_date"] = fmt(base_dt)
    liab["csed_effective_date"] = fmt(base_dt)


def overlap_with_existing_closed(liability_id: str, start_iso: str, end_iso: str) -> bool:
    """Determine whether [start, end) overlaps any existing tolling interval on this liability."""
    s = parse_iso(start_iso)
    e = parse_iso(end_iso)
    for evt in _events_for(liability_id):
        es = parse_iso(evt["start_date"])
        ee = parse_iso(evt["end_date"]) if evt.get("end_date") else CLOCK.now()
        # Half-open overlap: not (e <= es OR s >= ee)
        if not (e <= es or s >= ee):
            return True
    return False
