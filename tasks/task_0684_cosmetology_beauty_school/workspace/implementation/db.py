"""In-memory data store (PRD 2.4 / 2.5).

ALL state is held in process memory. Nothing is persisted; every byte is wiped
when the process restarts (the test harness reboots the server before each test).
The store starts EMPTY — no entity is seeded, preloaded, or hardcoded at startup.
"""
import uuid

import clock

# One dict per primary collection, keyed by id.
programs = {}
students = {}
instructors = {}
stations = {}
enrollments = {}
attendance_records = {}
clinic_tickets = {}
station_assignments = {}
disbursements = {}
exam_applications = {}
withdrawals = {}

# Monotonic creation sequence — a deterministic total creation order that is
# independent of timestamp collisions (the logical clock can be frozen, so many
# rows can share an identical created_at). Used only as the stable realization
# of the PRD's "created_at ASC" list ordering.
_seq = {"n": 0}


def reset():
    for d in (
        programs, students, instructors, stations, enrollments,
        attendance_records, clinic_tickets, station_assignments,
        disbursements, exam_applications, withdrawals,
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


def stamp_new(row):
    """Populate system fields (id/created_at/updated_at/version) on a new row.

    PRD 2.4: every entity carries a UUID id (no type prefix), a created_at,
    an updated_at, and an integer version that begins at 1 on creation.
    """
    ts = now_iso()
    row["id"] = new_id()
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    row["_seq"] = _next_seq()
    return row


def touch(row):
    """Mutation bump: increment version by exactly one and refresh updated_at."""
    row["version"] += 1
    row["updated_at"] = now_iso()
    return row
