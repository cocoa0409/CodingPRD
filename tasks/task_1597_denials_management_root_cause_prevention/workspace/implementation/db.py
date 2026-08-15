"""In-memory data store and logical clock.

Storage is process-local dicts keyed by id. Nothing is persisted to disk;
every start.sh re-invocation boots with an empty store and the default
logical clock of 2026-08-01T00:00:00Z.
"""

import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


class Store:
    def __init__(self):
        self.payers = {}
        self.policies = {}
        self.remittance_codes = {}
        self.denials = {}
        self.appeals = {}
        self.attachments = {}
        self.tasks = {}
        self.writeoffs = {}
        self.scorecards = {}
        self.programs = {}
        self.events = {}
        self.seq = 0
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def next_seq():
    store.seq += 1
    return store.seq


def new_id():
    return str(uuid.uuid4())
