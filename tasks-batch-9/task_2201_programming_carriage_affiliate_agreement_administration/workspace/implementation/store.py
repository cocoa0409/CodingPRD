"""In-memory data store and shared time / numeric helpers.

The store is a set of plain dicts keyed by id.  It starts COMPLETELY EMPTY on
every boot: nothing is seeded, preloaded or hardcoded.  Every entity is created
through the declared API surface.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from constants import DEFAULT_LOGICAL_CLOCK

PERIOD_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")
TERRITORY_RE = re.compile(r"^[A-Z]{2}$")


# ---------------------------------------------------------------------------
# datetime helpers
# ---------------------------------------------------------------------------
def parse_iso(value):
    """Parse an ISO-8601 UTC instant.  Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    txt = raw
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """Render an instant as ISO-8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def month_first_day(year, month):
    return datetime(year, month, 1, tzinfo=timezone.utc)


def period_first_day(period_month):
    year, month = int(period_month[:4]), int(period_month[5:7])
    return month_first_day(year, month)


def period_last_day(period_month):
    """First instant of the last calendar day of the given YYYY-MM."""
    year, month = int(period_month[:4]), int(period_month[5:7])
    if month == 12:
        nxt = month_first_day(year + 1, 1)
    else:
        nxt = month_first_day(year, month + 1)
    return nxt - timedelta(days=1)


def month_key(dt):
    return "%04d-%02d" % (dt.year, dt.month)


def add_months(dt, months):
    total = (dt.year * 12 + (dt.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    day = dt.day
    # clamp to the last day of the destination month
    if month == 12:
        nxt = month_first_day(year + 1, 1)
    else:
        nxt = month_first_day(year, month + 1)
    last = (nxt - timedelta(days=1)).day
    if day > last:
        day = last
    return dt.replace(year=year, month=month, day=day)


def whole_months_between(start, end):
    """Whole calendar months elapsed from `start` to `end` (never negative)."""
    if end <= start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    anchor = add_months(start, months)
    if anchor > end:
        months -= 1
    return max(0, months)


def floor_days(later, earlier):
    """Whole days from `earlier` to `later`, fraction discarded (may be < 0)."""
    delta = later - earlier
    # timedelta normalises so days*86400 + seconds is already the floor of the
    # total elapsed seconds at whole-second resolution, for either sign.
    seconds = delta.days * 86400 + delta.seconds
    return seconds // 86400


# ---------------------------------------------------------------------------
# numeric helpers
# ---------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places):
    """Round half up at `places` decimal places."""
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def dfloor(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def clamp(value, low, high):
    value = D(value)
    if value < D(low):
        return D(low)
    if value > D(high):
        return D(high)
    return value


# ---------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.distributors = {}
        self.agreements = {}
        self.rate_card_entries = {}
        self.mfn_clauses = {}
        self.subscriber_reports = {}
        self.audit_engagements = {}
        self.audit_findings = {}
        self.content_titles = {}
        self.rights_windows = {}
        self.blackout_rules = {}
        self.marketing_commitments = {}
        self.invoices = {}
        self.renewal_analyses = {}
        self.clock = {
            "current_utc": parse_iso(DEFAULT_LOGICAL_CLOCK),
            "set_count": 0,
        }
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The server's logical now.  Never falls back to wall-clock time."""
    return db.clock["current_utc"]


def new_id():
    return str(uuid.uuid4())


def new_entity(versioned=True, created=True):
    rec = {"id": new_id(), "_seq": db.next_seq()}
    if created:
        rec["created_at"] = now()
    if versioned:
        rec["updated_at"] = now()
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version, exactly as a direct write would."""
    if rec is None:
        return
    if "version" in rec:
        rec["version"] = rec["version"] + 1
    if "updated_at" in rec:
        rec["updated_at"] = now()


def creation_order(records):
    return sorted(records, key=lambda r: (r.get("created_at") or now(), r["_seq"]))


def serialize(rec):
    """Public JSON projection: internal keys (leading underscore) are hidden."""
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        out[key] = _to_json(value)
    return out


def _to_json(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        as_int = value.to_integral_value()
        if value == as_int:
            # keep whole-cent amounts and integral rates readable
            return float(value)
        return float(value)
    if isinstance(value, dict):
        return {k: _to_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_json(v) for v in value]
    return value
