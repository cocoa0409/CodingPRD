"""In-memory store, id minting, the logical clock and timestamp rendering.

Storage is plain Python dicts keyed by id.  Nothing is persisted anywhere; a
fresh process starts with every collection empty and no entity is ever seeded.

TIMESTAMP RULE (applied everywhere, no exceptions):
  * Any instant the SERVER writes -- i.e. anything read from the logical clock
    or computed by arithmetic on it (created_at, updated_at, signed_at,
    checked_out_at, attested_at, recalled_at, discharged_at, sla_due_at,
    last_reauthorized_at, last_appeal_attempt_at, prescription_changed_at,
    started_at, mastered_at, returned_at, recall_due_at, responded_at) -- is
    rendered as ISO 8601 UTC with EXACTLY three fractional-second digits:
    "YYYY-MM-DDTHH:MM:SS.sssZ"   (PRD §2.4).
  * Any instant the CALLER supplies (scheduled_start_at, scheduled_end_at,
    performed_at, credential_expires_at, due_at) is stored and echoed back
    BYTE FOR BYTE as supplied -- never reformatted.
  * The logical-clock endpoint echoes `current_utc` exactly as the caller
    supplied it in `to_iso8601`, and exactly "2026-05-01T00:00:00Z" before any
    caller has set it (PRD §2.5 states that literal reading).
"""

import random
import re
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone

import config

_lock = threading.Lock()
_seq_counter = 0


def next_seq():
    """Monotonic insertion counter used as the deterministic tie-break for
    'greatest created_at, last one created wins'."""
    global _seq_counter
    with _lock:
        _seq_counter += 1
        return _seq_counter


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# ------------------------------------------------------------ ISO 8601 ----
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    y, mo, d, h, mi, s, frac, tz = m.groups()
    try:
        micro = 0
        if frac:
            micro = int(round(float(frac) * 1_000_000))
        dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        tz_body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(tz_body[:2]), minutes=int(tz_body[2:]))
        dt = dt - sign * offset
    return dt


def parse_date(value):
    """Parse an ISO 8601 calendar date into a `date`, or None."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
    except ValueError:
        return None


def iso3(dt):
    """Render a datetime as ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


# -------------------------------------------------------- logical clock ----
class Clock(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.dt = parse_instant(config.DEFAULT_LOGICAL_CLOCK_UTC)
        self.raw = config.DEFAULT_LOGICAL_CLOCK_UTC

    def set(self, raw, dt):
        self.raw = raw
        self.dt = dt

    def now(self):
        return self.dt

    def now_iso(self):
        return iso3(self.dt)


clock = Clock()


def now():
    return clock.now()


def now_iso():
    return clock.now_iso()


# ------------------------------------------------------------- the store ----
class Store(object):
    COLLECTIONS = (
        "patients", "payers", "coverages", "authorizations", "therapists", "rooms",
        "assessments", "measurements", "plans", "phases", "sessions",
        "kit_items", "kit_loans", "claims", "referrals", "occlusions",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})


db = Store()


def ordered(collection, predicate=None):
    """Every list default-sorts by created_at ascending; insertion order breaks ties."""
    rows = [r for r in collection.values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def latest(rows, key="created_at"):
    """Greatest `key`, with the last one created winning any tie."""
    best = None
    for r in rows:
        if r.get(key) is None:
            continue
        if best is None or (r[key], r["_seq"]) > (best[key], best["_seq"]):
            best = r
    return best


def base_row(with_version=True):
    row = {
        "id": new_id(),
        "_seq": next_seq(),
        "created_at": now_iso(),
    }
    if with_version:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Mutating a row bumps its version by exactly 1 and refreshes updated_at
    (PRD §2.4).  A row written several times inside one request counts as one
    mutation, so its version advances by exactly 1 for that call."""
    from flask import g

    if row is None or "version" not in row:
        return
    try:
        seen = g._touched
    except (AttributeError, RuntimeError):
        seen = None
    if seen is None:
        seen = set()
        try:
            g._touched = seen
        except RuntimeError:
            pass
    if row["id"] not in seen:
        seen.add(row["id"])
        row["version"] += 1
    row["updated_at"] = now_iso()
