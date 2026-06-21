"""In-memory data store. Starts EMPTY on every boot — no seeding.

All entities are top-level dicts keyed by their server-minted UUID. Ordering
for list endpoints is by created_at ASC; we preserve insertion order (dicts are
ordered in Python 3.7+) and created_at is monotonic with insertion, so the two
agree.
"""
import threading
import uuid
from datetime import timezone


class Store:
    def __init__(self):
        self.instructors = {}
        self.learners = {}
        self.courses = {}
        self.lessons = {}
        self.coupons = {}
        self.bundles = {}
        self.enrollments = {}
        self.lesson_completions = {}
        self.certificates = {}
        self.reviews = {}
        self.payouts = {}
        self.ledger_entries = {}
        self.lock = threading.RLock()
        # Monotonic counter to break created_at ties deterministically when two
        # entities are created at the same clock instant.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly 3 fractional digits and a trailing Z."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
