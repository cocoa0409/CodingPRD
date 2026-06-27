"""In-memory data store. Keyed by id. Starts empty on every boot — no seeding."""
import uuid

from clock import clock, iso_millis


class DB:
    def __init__(self):
        self.clients = {}
        self.therapists = {}
        self.licenses = {}
        self.intakes = {}
        self.matches = {}
        self.subscriptions = {}
        self.billing_cycles = {}
        self.session_credits = {}
        self.live_sessions = {}
        self.threads = {}
        self.messages = {}
        self.crisis_escalations = {}
        self.aid_applications = {}
        self.superbills = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def new_id():
    return str(uuid.uuid4())


def common_create_fields(versioned=True):
    """System fields stamped at creation. created_at/updated_at from logical clock."""
    now = iso_millis(clock.now())
    fields = {
        "id": new_id(),
        "created_at": now,
    }
    if versioned:
        fields["updated_at"] = now
        fields["version"] = 1
    fields["_seq"] = db.next_seq()
    return fields


def light_create_fields():
    """For SessionCredit and Message: only id + created_at (no updated_at, no version)."""
    now = iso_millis(clock.now())
    return {
        "id": new_id(),
        "created_at": now,
        "_seq": db.next_seq(),
    }


def touch(entity):
    """Mark a versioned entity as mutated: bump updated_at and version."""
    entity["updated_at"] = iso_millis(clock.now())
    entity["version"] = entity.get("version", 1) + 1
