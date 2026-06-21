import uuid

from clock import clock
from response import iso_ms


class DB:
    """In-memory store. Starts empty on every boot; no seeding."""

    def __init__(self):
        self.providers = {}
        self.payers = {}
        self.members = {}
        self.requests = {}            # AuthorizationRequest
        self.evidence = {}            # ClinicalEvidence
        self.decisions = {}           # ReviewDecision
        self.sessions = {}            # PeerToPeerSession
        self.reviewers = {}
        self.appeals = {}

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()
db._seq = 0


def new_common(with_version=True):
    """System-managed common fields. created_at/updated_at carry ms precision."""
    now = clock.now()
    fields = {
        "id": db.new_id(),
        "created_at": iso_ms(now),
        "_created_dt": now,            # internal: for sorting / interval math
        "_created_seq": db.next_seq(), # internal: monotonic creation order
    }
    if with_version:
        fields["updated_at"] = iso_ms(now)
        fields["version"] = 1
    return fields


def touch(entity):
    """Refresh updated_at and bump version on a mutation."""
    entity["updated_at"] = iso_ms(clock.now())
    entity["version"] = entity.get("version", 1) + 1
