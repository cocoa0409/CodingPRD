"""In-memory data store.

Storage is process-memory only: plain dicts keyed by id.  The store starts
completely empty on every boot — nothing is ever seeded, preloaded or
hardcoded here.  Every entity is created by clients through the declared
endpoints.
"""

import uuid

from clock import clock


class Store:
    def __init__(self):
        self.developers = {}
        self.reviewers = {}
        self.properties = {}
        self.projects = {}
        self.part_applications = {}
        self.findings = {}
        self.cost_line_items = {}
        self.amendments = {}
        self.investor_interests = {}
        self.credit_claims = {}
        self.recapture_events = {}
        self.compliance_covenants = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def base_record(with_mutation_fields=True):
    """id + created_at (+ updated_at / version when the entity carries them)."""
    rec = {"id": new_id(), "created_at": clock.now_iso()}
    if with_mutation_fields:
        rec["updated_at"] = clock.now_iso()
        rec["version"] = 1
    rec["_seq"] = store.next_seq()
    return rec


def touch(rec):
    """PRD 2.4 / 2.7: any mutation refreshes updated_at and increments version."""
    rec["updated_at"] = clock.now_iso()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def public(rec, extra=None):
    out = {k: v for k, v in rec.items() if not k.startswith("_")}
    if extra:
        out.update(extra)
    return out


def ordered(values):
    """Default list ordering: created_at ascending (insertion order breaks ties)."""
    return sorted(values, key=lambda r: (r["created_at"], r["_seq"]))
