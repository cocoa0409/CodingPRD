"""In-memory data store and the logical clock (PRD 2.4, 2.5).

Storage is process-local Python dicts keyed by id.  Nothing is seeded: every
entity is created by a client through the declared endpoints.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

# PRD 2.5 - on startup the logical clock reads exactly 2026-08-01T00:00:00Z and
# never falls back to real wall-clock time.
CLOCK_ORIGIN = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


class Store:
    def __init__(self):
        self.markets = {}
        self.artists = {}
        self.venues = {}
        self.shows = {}
        self.offers = {}
        self.budget_lines = {}
        self.vendor_invoices = {}
        self.ticket_tiers = {}
        self.ticket_holds = {}
        self.settlements = {}
        self.cancellation_events = {}
        self.clock = CLOCK_ORIGIN
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    return db.clock


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_ts(value):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, tzs = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        dt = datetime(
            int(year), int(month), int(day), int(hour), int(minute),
            int(second or 0), micro, tzinfo=UTC,
        )
    except ValueError:
        return None
    if tzs and tzs not in ("Z", "z"):
        sign = 1 if tzs[0] == "+" else -1
        body = tzs[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * offset
    return dt


def new_entity(**fields):
    stamp = now()
    entity = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }
    entity.update(fields)
    return entity


def touch(entity):
    """A mutation: bump version by exactly 1 and refresh updated_at."""
    if entity is None:
        return
    entity["version"] += 1
    entity["updated_at"] = now()


def by_seq(rows):
    """List ordering: created_at ascending (PRD 2.3), insertion order breaking ties."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------
# reverse lookups
# --------------------------------------------------------------------------

def shows_of_market(market_id):
    return [s for s in db.shows.values() if s["market_id"] == market_id]


def shows_of_artist(artist_id):
    return [s for s in db.shows.values() if s["artist_id"] == artist_id]


def offers_of_show(show_id):
    return by_seq([o for o in db.offers.values() if o["show_id"] == show_id])


def accepted_offer(show_id):
    for o in offers_of_show(show_id):
        if o["status"] == "ACCEPTED":
            return o
    return None


def lines_of_show(show_id):
    return by_seq([b for b in db.budget_lines.values() if b["show_id"] == show_id])


def live_lines_of_show(show_id):
    """Lines that participate in settlement math: status ACTIVE or SETTLED."""
    return [b for b in lines_of_show(show_id) if b["status"] != "VOID"]


def invoices_of_line(line_id):
    return by_seq([i for i in db.vendor_invoices.values()
                   if i["budget_line_id"] == line_id])


def invoices_of_show(show_id):
    return by_seq([i for i in db.vendor_invoices.values()
                   if i["show_id"] == show_id])


def tiers_of_show(show_id):
    return by_seq([t for t in db.ticket_tiers.values() if t["show_id"] == show_id])


def holds_of_tier(tier_id):
    return by_seq([h for h in db.ticket_holds.values()
                   if h["ticket_tier_id"] == tier_id])


def settlements_of_show(show_id):
    return by_seq([s for s in db.settlements.values() if s["show_id"] == show_id])


def paid_settlement(show_id):
    for s in settlements_of_show(show_id):
        if s["status"] == "PAID":
            return s
    return None


def events_of_show(show_id):
    return by_seq([e for e in db.cancellation_events.values()
                   if e["show_id"] == show_id])
