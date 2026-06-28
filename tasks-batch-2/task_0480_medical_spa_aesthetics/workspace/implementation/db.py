"""In-memory data store. Starts empty on every boot. No seeding."""
import itertools
import uuid
from datetime import datetime, timezone


class DB:
    def __init__(self):
        self.providers = {}
        self.membership_packages = {}
        self.injectable_lots = {}
        self.patients = {}
        self.loyalty_accounts = {}
        self.consultations = {}
        self.standing_orders = {}
        self.treatment_plans = {}
        self.deposits = {}
        self.treatment_sessions = {}
        self.consent_photos = {}
        self.complication_cases = {}
        # monotonic counter to provide a stable insertion order / created_at tiebreak
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = DB()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Real wall-clock timestamp for created_at/updated_at (system bookkeeping).

    The logical clock governs domain expiry checks only; resource audit
    timestamps use real time per PRD §2.4 (created_at set when persisted).
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"
