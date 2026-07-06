"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone

STARTUP_CLOCK_DEFAULT = "2026-05-01T00:00:00Z"


class Store:
    def __init__(self):
        self.centers = {}
        self.clinicians = {}
        self.chambers = {}
        self.payer_policies = {}
        self.patients = {}
        self.referrals = {}
        self.wound_assessments = {}
        self.photo_documents = {}
        self.treatment_plans = {}
        self.prior_authorizations = {}
        self.debridement_procedures = {}
        self.hbo_sessions = {}
        self.supply_orders = {}
        self.acute_transfers = {}
        self.outcome_reports = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"
