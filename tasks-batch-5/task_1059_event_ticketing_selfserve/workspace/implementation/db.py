"""In-memory data store and logical clock.

The store starts EMPTY on every boot. No entity is seeded, preloaded or
hardcoded anywhere in this module or at application startup.
"""
import datetime
import uuid

DEFAULT_CLOCK = datetime.datetime(2026, 7, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)

COLLECTIONS = [
    "organizers",
    "venues",
    "buyers",
    "events",
    "ticket_types",
    "seat_blocks",
    "promo_codes",
    "orders",
    "order_items",
    "attendees",
    "scans",
    "refund_requests",
    "transfer_requests",
    "waitlist_entries",
    "payouts",
]


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
def now():
    """Current instant as read from the server-side logical clock."""
    return store.clock


def set_clock(dt):
    store.clock = dt


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 UTC instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def now_iso():
    return iso(now())


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def base_record(with_version=True):
    stamp = now_iso()
    rec = {"id": new_id(), "created_at": stamp, "_seq": store.next_seq()}
    if with_version:
        rec["updated_at"] = stamp
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and advance version by exactly 1."""
    if "version" in rec:
        rec["updated_at"] = now_iso()
        rec["version"] += 1
    return rec


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def ordered(records):
    """Default ordering: created_at ascending (stable by insertion sequence)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
