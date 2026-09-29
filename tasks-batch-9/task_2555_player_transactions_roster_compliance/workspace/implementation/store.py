"""In-memory data store, logical clock and identity helpers."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

# PRD 2.5: at boot the logical clock reads exactly this instant.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "teams",
    "players",
    "contracts",
    "bonus_allocations",
    "transactions",
    "waiver_requests",
    "waiver_claims",
    "trades",
    "trade_assets",
    "qualifying_offers",
    "injury_designations",
    "physical_exams",
    "compliance_checks",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The logical clock. Nothing in this system reads the host wall clock."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def fmt_ms(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_ts(dt):
    """PRD 2.4: an ISO 8601 UTC instant is rendered with exactly three
    fractional-second digits. Snapped deadlines still carry no sub-second
    component (PRD 2.5) - that truncation happens on the stored value."""
    return fmt_ms(dt)


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def base_record():
    stamp = db.clock
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(record):
    """Any write that changes a resource refreshes updated_at and version."""
    record["updated_at"] = db.clock
    record["version"] = record.get("version", 1) + 1
    return record


def values(collection, predicate=None):
    items = list(collection.values())
    if predicate is not None:
        items = [item for item in items if predicate(item)]
    items.sort(key=lambda item: (item["created_at"], item["_seq"]))
    return items


def hours(count):
    return timedelta(hours=count)


def days(count):
    return timedelta(days=count)
