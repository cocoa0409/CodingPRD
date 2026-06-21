"""In-memory data store. Starts empty on every boot; no seeding."""
import itertools
import uuid
from datetime import datetime, timezone


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


class Store:
    """Holds all entity collections keyed by id, plus an insertion sequence
    used to preserve creation order for list pagination."""

    def __init__(self):
        self.orgs = {}
        self.payers = {}
        self.sanctions_sources = {}
        self.providers = {}
        self.credential_items = {}
        self.verification_requests = {}
        self.sanctions_screenings = {}
        self.credentialing_files = {}
        self.peer_reviewers = {}
        self.peer_review_votes = {}
        self.payer_enrollments = {}
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


# Single module-level store instance; replaced fresh per process boot.
store = Store()
