"""In-memory data store, logical clock, id/sequence minting, datetime helpers.

All state lives in module-level dicts that are re-created on every process
start, so a fresh `bash start.sh` invocation always wipes prior state. No entity
is ever seeded here — every record is created by an API request.
"""
import uuid
import secrets
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        # Each collection maps id -> record dict.
        self.programs = {}
        self.consumers = {}
        self.matches = {}
        self.claims = {}
        self.documents = {}
        self.payouts = {}
        self.fraud_flags = {}
        self.fund_transactions = {}
        self.notifications = {}
        self.assessments = {}
        self._seq = 0
        self.clock = DEFAULT_CLOCK

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock


store = Store()


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + secrets.token_hex(12)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO-8601 datetime; returns aware UTC datetime or raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
