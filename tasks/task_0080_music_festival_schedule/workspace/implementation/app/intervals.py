"""The four interval-arithmetic flavours from PRD §3.5.

Each function takes the candidate interval and the set of existing
intervals and returns ``True`` when there is a conflict.  The caller
maps the boolean to the right ERR_* id from §1.6.

Flavour 1: stage-changeover overlap.  Half-open candidate
[start, end) versus a closed existing interval padded on both sides by
the stage's `changeover_buffer_seconds` (default
STAGE_CHANGEOVER_BUFFER_SECONDS = 1800 s).

Flavour 2: equipment-kit aggregate-capacity sweep.  A standard
sweep-line over `(time, +1)` openings and `(time, -1)` closings sorted
by `(time, closing-before-opening-at-equal-time)`, giving the maximum
number of simultaneously-active intervals during the candidate's
half-open window.

Flavour 3: sound-engineer-team closed-closed-symmetric-padded.  The
team's existing slots in {SCHEDULED, COMPLETED} are closed-closed
intervals padded symmetrically by ``warmup_minutes * 60`` seconds; the
candidate's closed-closed interval must not intersect any of them.

Flavour 4: rehearsal-room half-open-same-string.  Two ROOM rehearsals
with the same `rehearsal_room_name` and overlapping half-open windows
conflict.  STAGE and ROOM are disjoint namespaces.
"""
from __future__ import annotations

from typing import Iterable, Sequence, Tuple

from .constants import (
    STAGE_CHANGEOVER_BUFFER_SECONDS,
    TEAM_WARMUP_MINUTES,
)


# ---------------------------------------------------------------------------
# Flavour 1: stage changeover overlap.
# ---------------------------------------------------------------------------


def stage_changeover_conflict(
    candidate: Tuple[int, int],
    existing_intervals: Iterable[Tuple[int, int]],
    buffer_seconds: int = STAGE_CHANGEOVER_BUFFER_SECONDS,
) -> bool:
    """Return True iff the half-open candidate intersects any padded-closed existing.

    Boundary asymmetry pinned by PRD §3.5: the existing's right padding
    is **inclusive** (a candidate starting exactly at ``existing.end +
    buffer`` conflicts) and the candidate's right end is **exclusive**
    (an existing whose padded left edge is exactly ``candidate.end``
    does **not** conflict because the candidate's right is open).
    """
    c_start, c_end = candidate
    for e_start, e_end in existing_intervals:
        padded_left = e_start - buffer_seconds
        padded_right = e_end + buffer_seconds
        # `candidate.start <= padded_right` AND `padded_left < candidate.end`.
        if c_start <= padded_right and padded_left < c_end:
            return True
    return False


# ---------------------------------------------------------------------------
# Flavour 2: equipment-kit aggregate-capacity sweep.
# ---------------------------------------------------------------------------


def equipment_kit_peak_concurrent(
    candidate: Tuple[int, int],
    existing_intervals: Sequence[Tuple[int, int]],
) -> int:
    """Return the peak concurrent existing-interval count over the candidate window.

    The "+1" for the candidate itself is the caller's responsibility — this
    function returns the maximum over time of the count of existing intervals
    overlapping the candidate's half-open ``[c_start, c_end)`` window.  The
    sweep tie-breaks closings before openings at equal time, which is the
    standard half-open-right-exclusive disambiguation: back-to-back intervals
    that share an instant do not count as overlapping at the joint instant.
    """
    c_start, c_end = candidate
    events: list[tuple[int, int]] = []
    # We're interested in the running count of existing intervals at every
    # event time, then bracketed to the candidate's half-open window.
    for e_start, e_end in existing_intervals:
        # Clip to the candidate's window so the peak only considers overlap
        # **during** the candidate.  An existing interval entirely before
        # the candidate contributes nothing.
        if e_end <= c_start:
            continue
        if e_start >= c_end:
            continue
        # The interval ``[max(e_start, c_start), min(e_end, c_end))`` is
        # what overlaps the candidate's window.  Both events still respect
        # the close-before-open-at-equal-time rule, sort key
        # ``(t, +0 for close before +1 for open)``.
        clipped_start = max(e_start, c_start)
        clipped_end = min(e_end, c_end)
        if clipped_start >= clipped_end:
            continue
        # ``+0`` for the close at ``clipped_end`` is the
        # close-before-open-at-equal-time disambiguation.  The standard
        # encoding is ``(t, kind)`` with kind 0 = close, 1 = open, sorted
        # ascending.
        events.append((clipped_start, 1))
        events.append((clipped_end, 0))
    events.sort(key=lambda ev: (ev[0], ev[1]))

    running = 0
    peak = 0
    for _t, kind in events:
        if kind == 0:
            running -= 1
        else:
            running += 1
        if running > peak:
            peak = running
    return peak


# ---------------------------------------------------------------------------
# Flavour 3: sound-engineer-team closed-closed warmup-padded.
# ---------------------------------------------------------------------------


def team_warmup_conflict(
    candidate: Tuple[int, int],
    existing_intervals: Iterable[Tuple[int, int]],
    warmup_minutes: int = TEAM_WARMUP_MINUTES,
) -> bool:
    """Return True iff the closed candidate intersects any warmup-padded closed existing.

    Both intervals are closed on both ends.  The existing is symmetrically
    padded by ``warmup_minutes * 60`` seconds.  Intersection: the candidate
    starts no later than the existing's padded right edge and the existing's
    padded left edge is no later than the candidate's right edge.
    """
    c_start, c_end = candidate
    pad = int(warmup_minutes) * 60
    for e_start, e_end in existing_intervals:
        left = e_start - pad
        right = e_end + pad
        if c_start <= right and left <= c_end:
            return True
    return False


# ---------------------------------------------------------------------------
# Flavour 4: rehearsal-room half-open same-name.
# ---------------------------------------------------------------------------


def rehearsal_room_conflict(
    candidate: Tuple[int, int],
    existing_intervals: Iterable[Tuple[int, int]],
) -> bool:
    """Standard half-open-right-exclusive overlap test.

    Back-to-back rehearsals on the same room (one ending exactly when the
    next begins) is allowed because the prior's `end_time` is exclusive.
    """
    c_start, c_end = candidate
    for e_start, e_end in existing_intervals:
        if c_start < e_end and e_start < c_end:
            return True
    return False


def half_open_overlaps(
    a: Tuple[int, int], b: Tuple[int, int]
) -> bool:
    """Generic half-open `[start, end)` overlap test, used by the artist rules."""
    a_start, a_end = a
    b_start, b_end = b
    return a_start < b_end and b_start < a_end


def within_window(
    inner: Tuple[int, int], outer: Tuple[int, int]
) -> bool:
    """`inner` is wholly contained within `outer`, both half-open.

    The §2.4 child-window containment rule: ``outer.start ≤ inner.start``
    AND ``inner.end ≤ outer.end``.
    """
    return outer[0] <= inner[0] and inner[1] <= outer[1]
