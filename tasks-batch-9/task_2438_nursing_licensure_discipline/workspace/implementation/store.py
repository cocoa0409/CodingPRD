"""In-memory store. Nothing is persisted and nothing is ever pre-seeded."""
import threading
import uuid
from datetime import datetime, timezone

from timeutil import UTC

STARTUP_CLOCK = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=UTC)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = STARTUP_CLOCK
        self.boards = {}
        self.programs = {}
        self.nurses = {}
        self.applications = {}
        self.licenses = {}
        self.renewals = {}
        self.ce_records = {}
        self.complaints = {}
        self.evidence_requests = {}
        self.agreements = {}
        self.proceedings = {}
        self.reports = {}
        self.license_seq = 0

    def next_license_number(self, state_code, credential_type):
        self.license_seq += 1
        return "%s-%s-%06d" % (state_code, credential_type, self.license_seq)


STORE = Store()


def new_id():
    return str(uuid.uuid4())


def base_fields():
    now = STORE.clock
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
