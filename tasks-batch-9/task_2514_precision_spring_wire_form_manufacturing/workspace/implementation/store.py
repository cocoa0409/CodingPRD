"""In-memory data store, id/timestamp minting and the logical shop clock.

Storage is process-local Python dicts keyed by id.  Nothing is persisted and
NOTHING is seeded: every entity the tests need is built through the declared
API surface.
"""

import itertools
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Collections (all empty at boot)
# ---------------------------------------------------------------------------
programs = {}
material_specs = {}
designs = {}
characteristics = {}
tooling_assets = {}
wire_lots = {}
machines = {}
setups = {}
runs = {}
inspection_records = {}
ovens = {}
batches = {}
submissions = {}
lots = {}

_seq = itertools.count(1)

# ---------------------------------------------------------------------------
# The logical shop clock (PRD 2.5) — starts at exactly 2026-08-01T00:00:00Z
# ---------------------------------------------------------------------------
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_EPOCH}


def clock_now():
    return _clock["now"]


def clock_set(value):
    _clock["now"] = value


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def clock_iso():
    return iso(clock_now())


def wall_now():
    return datetime.now(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def request_timestamp():
    return iso(wall_now())


def parse_iso8601(value):
    """Parse an ISO 8601 instant.  Returns an aware datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------
def base_row(with_common=True):
    """Create the identity / audit skeleton of a row.

    `with_common` False produces a write-once row: only `id` and `created_at`
    exist, and both `updated_at` and `version` are absent entirely (PRD 2.4).
    """
    now = wall_now()
    row = {"id": new_id(), "created_at": iso(now), "_seq": next(_seq)}
    if with_common:
        row["updated_at"] = iso(now)
        row["version"] = 1
    return row


def touch(row, bump_version=True):
    """Refresh updated_at, and advance version when the row carries one."""
    row["updated_at"] = iso(wall_now())
    if bump_version and "version" in row:
        row["version"] = row["version"] + 1
    return row


def touch_program(program):
    """CustomerProgram.version is written ONLY by the quote endpoint (PRD 2.4)."""
    program["updated_at"] = iso(wall_now())
    return program


def by_seq(rows):
    """Chronological (created_at ascending) ordering with a stable tie-break."""
    return sorted(rows, key=lambda r: r["_seq"])


def newest(rows):
    rows = list(rows)
    if not rows:
        return None
    return max(rows, key=lambda r: r["_seq"])


PUBLIC_SKIP = ("_seq",)


def public(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def public_list(rows):
    return [public(r) for r in rows]


def minutes(n):
    return timedelta(minutes=n)
