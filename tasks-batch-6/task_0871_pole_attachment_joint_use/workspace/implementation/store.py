"""In-memory data store.  Fresh boot == empty store; NO seeding at startup."""

import uuid

from clock import LOGICAL_CLOCK


class Store(object):
    def __init__(self):
        self.pole_owners = {}
        self.crews = {}
        self.poles = {}
        self.attachers = {}
        self.applications = {}
        self.surveys = {}
        self.attachments = {}
        self.findings = {}
        self.invoices = {}
        self.disputes = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_record(self, extra):
        """Build a record with the standard system-managed fields."""
        now = LOGICAL_CLOCK.now()
        rec = {
            "id": str(uuid.uuid4()),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": self.next_seq(),
        }
        rec.update(extra)
        return rec


def touch(rec):
    """Mark a record mutated: refresh updated_at and bump version."""
    rec["updated_at"] = LOGICAL_CLOCK.now()
    rec["version"] += 1


DB = Store()
