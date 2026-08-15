"""In-memory data store and logical clock.

Storage is in-memory only (Python dicts). The store starts empty on every
boot — no seeding of any kind. All server-stamped timestamps read the single
logical clock, never the wall clock.
"""

import uuid
from datetime import datetime, timezone

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.channels = {}
        self.content_assets = {}
        self.rights_grants = {}
        self.playlist_loops = {}
        self.playlist_entries = {}
        self.ad_breaks = {}
        self.fill_decisions = {}
        self.ad_campaigns = {}
        self.ad_creatives = {}
        self.house_ads = {}
        self.distributor_platforms = {}
        self.distribution_agreements = {}
        self.revenue_reports = {}
        self.viewership_events = {}
        self.channel_day_snapshots = {}
        # Monotonic insertion counter — deterministic tie-break for ordering
        # (created_at ties); never exposed and never an id.
        self.seq = 0
        # The single logical clock.
        self.clock = CLOCK_DEFAULT


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def now():
    return store.clock


def today():
    return store.clock.date()


def set_clock(dt):
    store.clock = dt


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_str():
    return fmt_dt(store.clock)


def touch(rec):
    """Refresh updated_at and bump version (called on every modification)."""
    rec["updated_at"] = now_str()
    rec["version"] = rec.get("version", 1) + 1
