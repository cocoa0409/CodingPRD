"""Trip segment management and the trip-end cascade (PRD §3.4, §3.5).

Segments are append-only event records (id + created_at only; PRD §2.4). The
trip keeps exactly one open segment at a time; pausing/resuming/ending closes
the open segment and (for pause/resume) opens the next.
"""
from clock import now, now_iso
from db import db, stamp_new
from services.mds import parse_iso


def open_segment(trip, segment_type, zone_id):
    """Open a new segment with started_at := now, ended_at := null."""
    seg = {
        "trip_id": trip["id"],
        "segment_type": segment_type,
        "zone_id": zone_id,
        "started_at": now_iso(),
        "ended_at": None,
        "duration_seconds": 0,
    }
    stamp_new(seg, versioned=False)
    db.trip_segments[seg["id"]] = seg
    return seg


def open_segment_of(trip):
    """Return the trip's currently-open segment (ended_at is null), or None."""
    open_segs = [
        s for s in db.trip_segments.values()
        if s["trip_id"] == trip["id"] and s.get("ended_at") is None
    ]
    if not open_segs:
        return None
    # At most one is open; pick the most recently created defensively.
    return max(open_segs, key=lambda s: s.get("_seq", 0))


def close_open_segment(trip):
    """Close the trip's open segment: stamp ended_at and duration_seconds."""
    seg = open_segment_of(trip)
    if seg is None:
        return None
    end = now()
    start = parse_iso(seg["started_at"])
    seg["ended_at"] = now_iso()
    seconds = int((end - start).total_seconds())
    seg["duration_seconds"] = max(0, seconds)
    return seg
