"""In-memory data store. Starts empty on every boot — no seeding.

Every entity is a plain dict keyed by its UUID id. Common system fields:
id, created_at, updated_at, version.
"""
import itertools
import uuid
from datetime import timezone

from clock import clock

# A monotonic counter pins list-sort order ("creation timestamp ascending")
# even when several entities are created within the same clock millisecond.
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def iso_now():
    now = clock.now().astimezone(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.centers = {}
        self.programs = {}
        self.belt_levels = {}
        self.badges = {}
        self.guardians = {}
        self.members = {}
        self.memberships = {}
        self.sessions = {}
        self.enrollments = {}
        self.badge_awards = {}
        self.showcases = {}
        self.showcase_entries = {}

    def make(self, fields):
        """Create a base entity dict with common system fields."""
        rec = {
            "id": new_id(),
            "created_at": iso_now(),
            "updated_at": iso_now(),
            "version": 1,
            "_seq": next(_seq),
        }
        rec.update(fields)
        return rec

    def touch(self, rec):
        """Mark a resource mutated: refresh updated_at + bump version."""
        rec["updated_at"] = iso_now()
        rec["version"] += 1


db = Store()
