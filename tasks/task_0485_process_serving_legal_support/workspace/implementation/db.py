"""In-memory data store.

All state is held in Python dicts keyed by id. There is NO persistence, no
seeding, and no preloaded entities — every entity is created by API calls. A
fresh process (start.sh re-invocation) wipes all state.
"""
import uuid

from clock import clock


class Store:
    def __init__(self):
        self.clients = {}
        self.counties = {}
        self.servers = {}
        self.server_territories = {}
        self.service_requests = {}
        self.documents = {}
        self.assignments = {}
        self.attempts = {}
        self.services = {}
        self.affidavits = {}
        self.skip_traces = {}
        self.stakeouts = {}
        self.filings = {}
        self.invoice_lines = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Current logical-clock timestamp, ISO 8601 UTC with three fractional digits."""
    dt = clock.get()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def base_fields(common=True):
    """System fields stamped at creation (PRD 2.4)."""
    ts = now_iso()
    fields = {"id": new_id(), "created_at": ts}
    if common:
        # Most entities carry updated_at and version. ServerTerritory does not.
        fields["updated_at"] = ts
        fields["version"] = 1
    return fields


def touch(entity):
    """Mark an entity mutated: refresh updated_at, bump version (PRD 2.4)."""
    if "version" in entity:
        entity["updated_at"] = now_iso()
        entity["version"] = entity["version"] + 1
