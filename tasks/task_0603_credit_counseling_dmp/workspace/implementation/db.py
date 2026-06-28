"""In-memory data store. Starts EMPTY on every boot -- no seeding."""
import itertools
import uuid
from datetime import datetime, timezone

_counter = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    # ISO 8601 UTC with exactly three fractional digits, trailing Z.
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def req_id():
    return "req_" + uuid.uuid4().hex[:20].upper()


def next_seq():
    # Monotonic creation sequence; used as a deterministic tiebreaker for sort
    # ordering when created_at timestamps collide within the same millisecond.
    return next(_counter)


class Store:
    def __init__(self):
        self.agencies = {}
        self.counselors = {}
        self.creditors = {}
        self.clients = {}
        self.sessions = {}
        self.debt_accounts = {}
        self.proposals = {}
        self.deposits = {}
        self.disbursement_runs = {}
        self.disbursement_lines = {}


db = Store()
