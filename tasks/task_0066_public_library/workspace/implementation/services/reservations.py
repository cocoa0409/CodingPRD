"""Reservation queue management and promotion cascades."""
from datetime import timedelta

import db
from clock import iso, now
from services.money import HOLD_PERIOD_DAYS


def _queued_for_title_sorted(book_title_id: str):
    """Return QUEUED reservations sorted by (created_at, id) ascending."""
    qs = [r for r in db.reservations.values()
          if r["book_title_id"] == book_title_id and r["status"] == "QUEUED"]
    qs.sort(key=lambda r: (r["created_at"], r["id"]))
    return qs


def _queued_for_title_by_position(book_title_id: str):
    """Return QUEUED reservations sorted by their assigned queue_position ascending."""
    qs = [r for r in db.reservations.values()
          if r["book_title_id"] == book_title_id and r["status"] == "QUEUED"]
    qs.sort(key=lambda r: (r.get("queue_position", 1 << 30), r["created_at"], r["id"]))
    return qs


def renumber_queued_positions(book_title_id: str):
    """Recompute queue_position for all QUEUED reservations on a title (1-indexed),
    preserving the existing relative order (sort by current queue_position first)."""
    qs = _queued_for_title_by_position(book_title_id)
    for idx, r in enumerate(qs, start=1):
        if r.get("queue_position") != idx:
            r["queue_position"] = idx
            r["updated_at"] = iso(now())
            r["version"] = r.get("version", 1) + 1


def next_queue_position(book_title_id: str) -> int:
    """Position assigned to a new reservation is one past the current last queue position.

    Per PRD §3.5: assigning the new reservation a 1-indexed position one past the
    last existing position. We compute it as count(QUEUED) + 1.
    """
    qs = _queued_for_title_sorted(book_title_id)
    return len(qs) + 1


def promote_next_head_for_copy(copy: dict) -> bool:
    """If a QUEUED reservation exists for this copy's title, promote it to READY_FOR_PICKUP
    and set copy.status = RESERVED. The head is the QUEUED reservation with the
    smallest queue_position. Returns True if a promotion occurred."""
    qs = _queued_for_title_by_position(copy["book_title_id"])
    if not qs:
        return False
    head = qs[0]
    head["status"] = "READY_FOR_PICKUP"
    head["held_copy_id"] = copy["id"]
    head["hold_expires_at"] = iso(now() + timedelta(days=HOLD_PERIOD_DAYS))
    head["updated_at"] = iso(now())
    head["version"] = head.get("version", 1) + 1
    copy["status"] = "RESERVED"
    copy["updated_at"] = iso(now())
    copy["version"] = copy.get("version", 1) + 1
    # Renumber remaining QUEUED reservations after the head leaves QUEUED
    renumber_queued_positions(copy["book_title_id"])
    return True


def release_copy_after_hold(copy: dict) -> bool:
    """Called when a held reservation is removed (expired/cancelled).
    If another QUEUED reservation exists for the same title, promote it; else set copy AVAILABLE.
    Returns True if a promotion occurred."""
    # First mark copy as AVAILABLE
    copy["status"] = "AVAILABLE"
    copy["updated_at"] = iso(now())
    copy["version"] = copy.get("version", 1) + 1
    # Then try to promote next
    return promote_next_head_for_copy(copy)


def active_reservation_exists_for_title(book_title_id: str, reader_id: str = None) -> bool:
    """Returns True if any reservation in QUEUED or READY_FOR_PICKUP for this title (optionally for this reader)."""
    for r in db.reservations.values():
        if r["book_title_id"] != book_title_id:
            continue
        if r["status"] not in {"QUEUED", "READY_FOR_PICKUP"}:
            continue
        if reader_id is None or r["reader_id"] == reader_id:
            return True
    return False
