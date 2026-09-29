"""In-memory data store.  Nothing is ever seeded: every collection starts empty
on every boot and is populated exclusively through the public API surface."""

import itertools
from datetime import datetime, timezone

DEFAULT_CURRENT_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "portfolios",
    "facilities",
    "tower_companies",
    "tower_sites",
    "landowners",
    "lease_streams",
    "tenancies",
    "valuations",
    "deals",
    "offers",
    "title_reports",
    "rofr_notices",
    "disputes",
    "pledges",
    "amendments",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.current_utc = DEFAULT_CURRENT_UTC
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()
