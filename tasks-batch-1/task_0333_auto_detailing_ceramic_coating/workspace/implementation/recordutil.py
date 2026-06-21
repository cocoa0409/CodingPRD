"""Helpers for record creation and creation-ordered listing."""
import clock
import db


def base_versioned():
    """Common system-managed fields for a versioned resource (§2.4):
    id, created_at, updated_at, version, and a monotonic _seq for stable ordering."""
    now = clock.now()
    return {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def base_catalog():
    """Common fields for an unversioned catalog resource (§2.4): id + created_at only."""
    return {
        "id": db.new_id(),
        "created_at": clock.now(),
        "_seq": db.next_seq(),
    }


def sorted_by_creation(records):
    """Sort by creation timestamp ascending; _seq breaks ties deterministically (§2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
