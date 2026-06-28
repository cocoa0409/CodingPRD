"""In-memory data store.

ALL state is held in process memory. Nothing is persisted; every byte is wiped
when the process restarts (the test harness reboots the server before each test).
The store starts EMPTY — no entity is seeded, preloaded, or hardcoded at startup.
"""
import uuid

import clock

# One dict per primary collection, keyed by id.
providers = {}
rooms = {}
patients = {}
encounters = {}
skin_exam_photos = {}
biopsies = {}
procedure_bookings = {}
prior_authorizations = {}
step_therapy_trials = {}
cosmetic_memberships = {}
cosmetic_treatments = {}
charges = {}
recall_reminders = {}

# Monotonic sequence to provide a deterministic, total creation order that is
# independent of timestamp collisions (the logical clock can be frozen, so many
# rows can share an identical created_at). Used only as a tie-stable creation
# order; PRD ordering rules are "created_at ASC" with creation order as the
# stable realization of that.
_seq = {"n": 0}


def reset():
    for d in (
        providers, rooms, patients, encounters, skin_exam_photos, biopsies,
        procedure_bookings, prior_authorizations, step_therapy_trials,
        cosmetic_memberships, cosmetic_treatments, charges, recall_reminders,
    ):
        d.clear()
    _seq["n"] = 0


def new_id():
    return str(uuid.uuid4())


def _next_seq():
    _seq["n"] += 1
    return _seq["n"]


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso(clock.now())


def stamp_new(row, common=True):
    """Populate system fields on a freshly-created row."""
    ts = now_iso()
    row["id"] = new_id()
    row["created_at"] = ts
    row["_seq"] = _next_seq()
    if common:
        row["updated_at"] = ts
        row["version"] = 1
    return row


def touch(row):
    """Mutation bump: refresh updated_at and increment version by exactly one."""
    if "version" in row:
        row["version"] += 1
    if "updated_at" in row:
        row["updated_at"] = now_iso()
    return row
