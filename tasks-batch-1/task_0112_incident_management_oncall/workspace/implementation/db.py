"""In-memory data store + logical clock. Empty on every boot — no seeding."""
import itertools
import threading
import uuid
from datetime import datetime, timezone

# Monotonic insertion counter. Used as the stable tie-break for list ordering
# when many records share a created_at (the logical clock is frozen during a
# test, so created_at alone does not preserve insertion order). Append-only
# logs (page attempts, war-room messages) must list in creation order.
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


class Clock:
    """Server-controlled logical clock (PRD 2.5).

    Starts at real wall-clock UTC; POST /_clock/set_current_utc pins it.
    Once pinned, now() returns the pinned instant (frozen, deterministic).
    """

    def __init__(self):
        self._fixed = None

    def set(self, dt):
        self._fixed = dt

    def now(self):
        if self._fixed is not None:
            return self._fixed
        return datetime.now(timezone.utc)


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = Clock()
        # one dict per entity kind, keyed by id
        self.services = {}
        self.responders = {}
        self.schedules = {}            # OnCallSchedule
        self.shifts = {}               # ScheduleShift
        self.policies = {}             # EscalationPolicy
        self.tiers = {}                # EscalationTier
        self.windows = {}              # MaintenanceWindow
        self.incidents = {}
        self.page_attempts = {}        # append-only
        self.war_rooms = {}
        self.war_room_messages = {}    # append-only
        self.postmortems = {}
        self.action_items = {}


db = DB()


def new_id():
    return str(uuid.uuid4())


def iso_ms(dt):
    """ISO 8601 UTC with three fractional digits, trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + "Z"


def iso_sec(dt):
    """ISO 8601 UTC stamped to whole seconds (.000 fractional)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
