import uuid
import threading

from clock import Clock


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = Clock()
        self._seq = 0
        # entity collections keyed by id
        self.clients = {}
        self.rate_plans = {}
        self.language_pairs = {}
        self.interpreters = {}
        self.certifications = {}
        self.interpreter_languages = {}
        self.requests = {}
        self.assignments = {}
        self.sessions = {}
        self.encounters = {}
        self.ratings = {}
        self.complaints = {}
        self.invoices = {}

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    def base_fields(self):
        now = self.clock.now_iso()
        return {
            "id": self.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": self.next_seq(),
        }

    def touch(self, entity):
        entity["updated_at"] = self.clock.now_iso()
        entity["version"] = entity.get("version", 1) + 1


db = DB()
