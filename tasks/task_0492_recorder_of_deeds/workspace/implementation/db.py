"""In-memory data store. Every collection is a dict keyed by entity id.
The store starts EMPTY on every boot — no seeding, no preloaded entities.
All entities are created by tests through the declared API surface."""
import uuid

from clock import iso, clock


class Store:
    def __init__(self):
        # one dict per entity collection, keyed by id
        self.offices = {}
        self.submitters = {}
        self.packages = {}
        self.party_entries = {}
        self.assessments = {}
        self.payments = {}
        self.recorded_documents = {}
        self.rejections = {}
        self.plats = {}
        self.ucc_filings = {}
        self.copy_search_requests = {}


db = Store()

_seq_counter = [0]


def _next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def new_id():
    return str(uuid.uuid4())


def common_fields():
    """created_at/updated_at on the logical clock; version starts at 1
    (PRD §2.4). _seq is an internal monotonic creation counter for stable
    list ordering when logical-clock timestamps coincide; never serialized."""
    now = clock.now()
    return {
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }


def touch(entity):
    """Refresh updated_at on the logical clock and bump version by 1.
    Generic mutation helper for entities whose version tracks every mutation."""
    entity["updated_at"] = clock.now()
    entity["version"] = entity["version"] + 1


def touch_no_version(entity):
    """Refresh updated_at only — used for DocumentPackage transitions that the
    PRD does NOT count as a version bump. DocumentPackage.version is the OCC
    anchor (PRD §2.4, §2.9) and is bumped ONLY at assessment-finalize and
    payment-capture, so other package mutations refresh the timestamp without
    advancing version."""
    entity["updated_at"] = clock.now()


# Datetime fields that need ISO serialization on output.
_DT_FIELDS = {
    "created_at",
    "updated_at",
    "recording_date",
    "recorded_on",
    "effective_date",
    "lapse_date",
}


def serialize(entity):
    """Return a JSON-safe copy: datetime fields -> ISO strings; internal
    underscore-prefixed keys (e.g. _seq) are omitted."""
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if k in _DT_FIELDS:
            out[k] = iso(v) if v is not None else None
        else:
            out[k] = v
    return out
