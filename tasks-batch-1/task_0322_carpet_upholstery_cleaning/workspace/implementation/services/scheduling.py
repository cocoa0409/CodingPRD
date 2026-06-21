"""Crew slot booking logic shared by /book and /reschedule (PRD §3.3).

The booking precondition order is fixed by PRD §2.6/§3.3 (the operation-specific
business rules run after the generic gates):
  1. crew AVAILABLE         -> ERR_CREW_UNAVAILABLE (409)
  2. service_type match     -> ERR_SERVICE_TYPE_MISMATCH (409)
  3. slot overlap (+buffer) -> ERR_SLOT_OVERLAP (409)
  4. expected_crew_version  -> ERR_STALE_CREW_VERSION (412)
"""
from __future__ import annotations

from typing import Dict

import db
from errors import (
    APIError,
    ERR_CREW_UNAVAILABLE,
    ERR_SERVICE_TYPE_MISMATCH,
    ERR_SLOT_OVERLAP,
    ERR_STALE_CREW_VERSION,
)
from services.common import init_common, touch


def _overlaps(crew: Dict, start_minute: int, end_minute: int) -> bool:
    """True if [start, end) collides with any RESERVED slot on the crew once
    each existing slot is extended at its tail by turnaround_buffer_minutes.

    A new slot beginning exactly at the buffer boundary (immediately after the
    buffer elapses) is adjacent, not overlapping, and is allowed. We extend
    EACH existing reserved slot's tail by the buffer, then test for true
    interval overlap of half-open intervals [a, b): overlap iff
    new_start < existing_end_with_buffer AND existing_start < new_end.
    """
    buf = crew["turnaround_buffer_minutes"]
    for s in db.scheduled_slots.values():
        if s["crew_id"] != crew["id"] or s["status"] != "RESERVED":
            continue
        ex_start = s["start_minute"]
        ex_end_buf = s["end_minute"] + buf
        # Half-open overlap test: adjacency at the buffer boundary is allowed.
        if start_minute < ex_end_buf and ex_start < end_minute:
            return True
    return False


def book_onto_crew(job: Dict, crew: Dict, start_minute: int, end_minute: int,
                   expected_crew_version: int) -> Dict:
    """Run the four booking checks in order, then create a RESERVED slot, point
    the job at it, and bump the crew version. Returns the new slot.

    Caller is responsible for the lifecycle-state transition and for releasing
    any prior slot (reschedule).
    """
    catalog = db.service_catalogs[job["service_catalog_id"]]

    # 1. crew availability
    if crew["status"] != "AVAILABLE":
        raise APIError(ERR_CREW_UNAVAILABLE, 409, "Crew is not AVAILABLE")
    # 2. service type match
    if crew["supported_service_type"] != catalog["service_type"]:
        raise APIError(ERR_SERVICE_TYPE_MISMATCH, 409, "Crew service type does not match job catalog")
    # 3. slot overlap
    if _overlaps(crew, start_minute, end_minute):
        raise APIError(ERR_SLOT_OVERLAP, 409, "Requested interval overlaps a reserved slot")
    # 4. OCC on crew version
    if expected_crew_version != crew["version"]:
        raise APIError(ERR_STALE_CREW_VERSION, 412, "Stale crew version")

    slot = init_common({
        "crew_id": crew["id"],
        "cleaning_job_id": job["id"],
        "start_minute": start_minute,
        "end_minute": end_minute,
        "status": "RESERVED",
    })
    db.scheduled_slots[slot["id"]] = slot
    job["scheduled_slot_id"] = slot["id"]
    touch(crew)  # crew.version += 1
    return slot
