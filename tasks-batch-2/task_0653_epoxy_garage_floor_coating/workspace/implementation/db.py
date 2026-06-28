"""In-memory data store. State is wiped on every fresh process boot.

NO seeding, preloading, or hardcoded entities — every entity is created by
tests via the declared API surface.
"""
import itertools
import secrets
import string
import uuid
from datetime import datetime, timezone

# Logical clock default (PRD §2.5): startup reads exactly this default and never
# falls back to host wall-clock time.
CLOCK_DEFAULT = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.coating_systems = {}
        self.color_options = {}
        self.financing_plans = {}
        self.crews = {}
        self.customers = {}
        self.projects = {}
        self.assessments = {}
        self.quotes = {}
        self.install_jobs = {}
        self.warranties = {}
        self.warranty_claims = {}
        self.referrals = {}

        # Monotonic creation sequence for stable created_at-ascending sort even
        # when multiple rows share the same logical-clock timestamp.
        self._seq = itertools.count(1)

        # Logical clock.
        self._clock = CLOCK_DEFAULT

    # ---- logical clock ----
    def now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt

    # ---- helpers ----
    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    """Server-minted UUID, no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    """req_ + random alphanumeric (PRD §2.2)."""
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def new_referral_code():
    """Short code other customers cite to credit this customer."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
