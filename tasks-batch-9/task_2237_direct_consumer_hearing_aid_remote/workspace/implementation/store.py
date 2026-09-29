"""In-memory data store, logical clock and record helpers.

Storage is purely in-process Python dicts keyed by id.  Nothing is seeded at
startup: every row is created by an API caller.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

TABLES = (
    "state_policies",
    "patients",
    "screening_sessions",
    "red_flag_findings",
    "providers",
    "provider_referrals",
    "remote_fitting_sessions",
    "device_orders",
    "devices",
    "trial_periods",
    "return_authorizations",
    "fit_exchanges",
    "inventory_pools",
    "repair_orders",
    "warranty_claims",
    "reimbursement_claims",
    "care_plan_subscriptions",
    "firmware_campaigns",
    "firmware_rollouts",
    "compliance_overrides",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_START
        self._seq = itertools.count(1)
        self._rma = itertools.count(1)
        for name in TABLES:
            setattr(self, name, {})

    def next_seq(self):
        return next(self._seq)

    def next_rma(self):
        return "RMA-%06d" % next(self._rma)


db = Store()


def now():
    return db.clock


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO-8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def days(n):
    return timedelta(days=n)


def minutes(n):
    return timedelta(minutes=n)


def base_record():
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def event_record():
    """RedFlagFinding is an immutable audit event: id + created_at only."""
    return {
        "id": new_id(),
        "created_at": now(),
        "_seq": db.next_seq(),
    }


def bump(rec):
    """Refresh updated_at and increment version on every mutation."""
    if rec is None:
        return rec
    rec["updated_at"] = now()
    rec["version"] = int(rec.get("version", 0)) + 1
    return rec


def serialize(value):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and k.startswith("_"):
                continue
            out[k] = serialize(v)
        return out
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    if isinstance(value, datetime):
        return iso(value)
    return value


def sort_key(rec):
    return (rec["created_at"], rec.get("_seq", 0))


def ordered(rows):
    return sorted(rows, key=sort_key)


def table_rows(table):
    return ordered(list(table.values()))
