import uuid
from response import iso_ms, now_dt


class DB:
    """In-memory data store. Starts EMPTY on every process boot.

    Every entity any test needs is constructed by the test via the declared API
    surface; nothing is seeded, preloaded, or hardcoded here.

    Entities are stored as plain dicts keyed by id, in separate collections.
    Python 3.7+ preserves dict insertion order, which we use (via _seq) as a
    stable tiebreak when created_at timestamps collide.
    """

    def __init__(self):
        self.veterans = {}
        self.claims = {}
        self.conditions = {}
        self.dependents = {}
        self.schools = {}
        self.enrollments = {}
        self.voc_rehab_plans = {}
        self._seq = 0  # monotonic insertion counter for stable ordering

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def now_iso():
    return iso_ms(now_dt())


def new_common(with_version=True):
    """Build the common server-managed fields for a freshly created entity.

    Most entities (Veteran, Claim, Condition, School, Enrollment, VocRehabPlan)
    carry id/created_at/updated_at/version (PRD §2.4). The Dependent is leaner:
    it carries only id/created_at (with_version=False) and never participates in
    OCC.
    """
    ts = now_iso()
    rec = {
        "id": db.new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump updated_at and version on a mutation (PRD §2.4 / §2.7).

    Never called on a version-less Dependent.
    """
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
