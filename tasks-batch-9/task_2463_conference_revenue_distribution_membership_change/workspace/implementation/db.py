"""In-memory store (PRD section 2.3 / 2.5).

Storage is plain Python dictionaries keyed by id.  Nothing is seeded: a fresh
boot holds zero entities and every record is built through the declared
endpoints.
"""

import uuid

import clock


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        # The conference is a singleton: one row, or None before initialisation.
        self.conference = None
        self.venues = {}
        self.members = {}
        self.revenue_pools = {}
        self.distribution_runs = {}
        self.distribution_lines = {}
        self.bowl_appearances = {}
        self.postseason_units = {}
        self.membership_actions = {}
        self.ballots = {}
        self.budget_proposals = {}
        self.protected_rivalries = {}
        self.schedule_games = {}
        self.championship_events = {}
        self.audit_reports = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_record(versioned=True):
    """Create the system fields every entity carries (PRD section 2.5)."""
    created = clock.now()
    record = {"id": new_id(), "created_at": created, "_seq": db.next_seq()}
    if versioned:
        record["updated_at"] = created
        record["version"] = 1
    return record


def touch(record):
    """Advance updated_at and version by exactly 1 (PRD section 2.5)."""
    record["updated_at"] = clock.now()
    record["version"] = record.get("version", 1) + 1


def ordered(records):
    """Creation order: created_at ascending, stable within equal instants."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
