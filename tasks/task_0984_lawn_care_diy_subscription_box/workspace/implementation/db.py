import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"


class Rec:
    """A stored entity record: plain attribute bag plus raw-echo map for
    input-provided datetime strings and an insertion sequence for stable
    created_at ordering."""

    def __init__(self, **kw):
        self.raw = {}
        self.__dict__.update(kw)


class Store:
    """Pure in-memory store. Starts completely empty on every boot; the
    logical clock reads exactly 2026-05-01T00:00:00Z until set."""

    def __init__(self):
        self.customers = {}
        self.lawns = {}
        self.soil_tests = {}
        self.plans = {}
        self.subscriptions = {}
        self.shipments = {}
        self.applications = {}
        self.weather_advisories = {}
        self.addons = {}
        self.claims = {}
        self.referrals = {}
        self.invoices = {}
        self.ledger = {}
        self.products = {}
        self.seq = 0
        self.clock = datetime(2026, 5, 1, tzinfo=timezone.utc)
        self.clock_raw = DEFAULT_CLOCK_ISO


store = Store()


def now():
    return store.clock


def next_seq():
    store.seq += 1
    return store.seq


def new_id():
    return str(uuid.uuid4())


def touch(rec, field_dt=None):
    """Bump version and updated_at on a mutable resource."""
    from util import fmt_dt3
    rec.version += 1
    rec.updated_at = now()
    rec.raw["updated_at"] = fmt_dt3(rec.updated_at)
    if field_dt:
        for f in field_dt:
            rec.raw[f] = fmt_dt3(getattr(rec, f))
