"""In-memory data store. Starts EMPTY on every boot. No seeding, ever.

Each entity type is a dict keyed by id. A monotonically increasing sequence
preserves creation order for ascending-by-created_at sorting (timestamps from
the logical clock can collide, so a sequence is the tiebreaker).
"""
import uuid
from datetime import datetime, timezone

import clock

divers = {}
instructors = {}
courses = {}
enrollments = {}
sessions = {}
session_bookings = {}
certification_cards = {}
waivers = {}
boats = {}
dive_trips = {}
trip_bookings = {}
rental_agreements = {}
fill_services = {}
gear_service_orders = {}

_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def _wall_iso():
    """Wall-clock ISO 8601 UTC, three fractional digits — for created_at /
    updated_at, which record real creation/modification time, not logical clock.
    PRD 2.4 ties only signed_at/issued_at/checkout_at/actual_return_at/serviced_at
    to the logical clock."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def clock_iso():
    """Logical-clock instant as ISO 8601 UTC with three fractional digits."""
    now = clock.get_now()
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def stamp_create(obj, common_fields=True):
    """Attach id + system fields on creation."""
    obj["id"] = new_id()
    obj["_seq"] = next_seq()
    if common_fields:
        ts = _wall_iso()
        obj["created_at"] = ts
        obj["updated_at"] = ts
        obj["version"] = 1
    else:
        # CertificationCard / Waiver: id + created_at only, no updated_at/version.
        obj["created_at"] = _wall_iso()
    return obj


def touch(obj):
    """Mutation: bump updated_at + version (common-field resources only)."""
    if "version" in obj:
        obj["updated_at"] = _wall_iso()
        obj["version"] += 1
