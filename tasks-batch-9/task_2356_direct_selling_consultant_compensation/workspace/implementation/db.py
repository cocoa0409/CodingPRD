"""In-memory data store. Starts completely empty on every boot: no seeding."""

import itertools
import threading
import uuid
from datetime import datetime, timezone

# Logical clock default, PRD section 2.5.
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

_seq_counter = itertools.count(1)
lock = threading.RLock()


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def wall_now():
    """Canonical ISO 8601 UTC with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Store:
    def __init__(self):
        self.clock = CLOCK_DEFAULT
        self.plans = {}
        self.jurisdictions = {}
        self.products = {}
        self.applications = {}
        self.consultants = {}
        self.orders = {}
        self.periods = {}
        self.qualifications = {}
        self.runs = {}
        self.statements = {}
        self.buybacks = {}
        self.cases = {}
        self.disclosures = {}


db = Store()
