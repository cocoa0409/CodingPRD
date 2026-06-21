"""In-memory data store.

Every collection is a plain dict keyed by UUID id. The store is constructed
fresh on every process boot and is NEVER seeded with business entities — tests
build all preconditions through the declared API surface. The only module-level
state is the empty collections below.
"""

import itertools
import uuid

from clock import now_iso

# Monotonic sequence used only to order resources deterministically by creation
# (creation timestamps can collide at millisecond resolution, especially under
# the test-driving clock which can freeze "now"). Sorting is by created_at then
# this sequence (see helpers).
_seq = itertools.count(1)

# ---- Collections (all start empty) ----------------------------------------
requesters = {}
officers = {}
appeal_authorities = {}
submitters = {}
requests = {}
records = {}
exemptions = {}
fee_estimates = {}          # keyed by FeeEstimate.id
deadlines = {}              # keyed by ProcessingDeadline.id
appeals = {}
objections = {}
reading_rooms = {}
review_stations = {}
reading_room_bookings = {}
review_station_bookings = {}
audit_events = {}

# Internal toll-window tracking: request_id -> open instant (datetime) of the
# currently-open advance-payment tolling window, or absent when not tolling.
toll_windows = {}


def new_id() -> str:
    return str(uuid.uuid4())


def next_seq() -> int:
    return next(_seq)


def stamp_create(obj: dict, *, versioned: bool = True) -> dict:
    """Attach the standard system fields on creation (PRD §2.4).

    versioned=False is used for the append-only Exemption / AuditEvent, which
    carry only id + created_at (no updated_at, no version).
    """
    ts = now_iso()
    obj.setdefault("id", new_id())
    obj["created_at"] = ts
    obj["_seq"] = next_seq()
    if versioned:
        obj["updated_at"] = ts
        obj.setdefault("version", 1)
    return obj


def touch(obj: dict) -> None:
    """Refresh updated_at and bump version on a mutation (PRD §2.4)."""
    obj["updated_at"] = now_iso()
    if "version" in obj:
        obj["version"] = obj["version"] + 1
