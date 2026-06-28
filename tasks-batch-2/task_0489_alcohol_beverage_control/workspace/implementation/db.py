"""In-memory data store. Every collection is a dict keyed by entity id.
The store starts EMPTY on every boot — no seeding, no preloaded entities.
All entities are created by tests through the declared API surface."""
import uuid
from datetime import timezone

from clock import iso, clock


class Store:
    def __init__(self):
        # one dict per entity collection, keyed by id
        self.license_classes = {}
        self.quota_regions = {}
        self.applicants = {}
        self.premises = {}
        self.license_applications = {}
        self.background_checks = {}
        self.zoning_reviews = {}
        self.protests = {}
        self.hearings = {}
        self.licenses = {}
        self.server_permits = {}
        self.violations = {}
        self.administrative_actions = {}
        self.compliance_reports = {}
        self.transfer_requests = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def common_fields():
    """created_at/updated_at on logical clock; version starts at 1."""
    now = clock.now()
    return {
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def touch(entity):
    """Refresh updated_at on the logical clock and bump version by 1."""
    entity["updated_at"] = clock.now()
    entity["version"] = entity["version"] + 1


# Fields that are datetime objects and need ISO serialization on output.
_DT_FIELDS = {
    "created_at", "updated_at", "submitted_at", "protest_period_ends_at",
    "resolved_at", "starts_at", "ends_at", "term_start_at", "term_end_at",
    "renewal_window_opens_at", "expires_at",
}


def serialize(entity):
    """Return a JSON-safe copy: datetime fields -> ISO strings."""
    out = {}
    for k, v in entity.items():
        if k in _DT_FIELDS:
            out[k] = iso(v) if v is not None else None
        else:
            out[k] = v
    return out
