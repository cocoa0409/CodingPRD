"""In-memory data store. Starts EMPTY on every process boot — no seeding."""
import uuid
import itertools

from response import now_iso

# Each table maps id -> dict record. Wiped on every fresh process start.
clubs = {}
categories = {}
memberships = {}
resources = {}
reservations = {}
chits = {}
guest_passes = {}
assessments = {}
assessment_charges = {}
waitlist_entries = {}
statements = {}

# Server logical clock (PRD §2.6 / §3.8). Default before any set call.
LOGICAL_CLOCK = ["2026-01-01T00:00:00Z"]

# Monotonic sequence to make created_at strictly orderable even when two
# records are created within the same millisecond. created_at strings are
# returned to clients; _seq is used internally as the tie-stable sort key.
_seq_counter = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


def base_record(common_fields=True):
    """Create the common audit fields. AssessmentCharge sets common_fields=False
    (only id + created_at, per PRD §2.4)."""
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": next_seq(),
    }
    if common_fields:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump version + refresh updated_at (a mutation)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
