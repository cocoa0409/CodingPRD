"""In-memory data store (PRD §2.4, §2.10).

The store starts completely empty on every boot. No entity is seeded, preloaded,
or hardcoded. Every record is created through the declared API surface.
"""
import uuid
from datetime import datetime, timezone


class DB:
    def __init__(self):
        # One dict per primary collection, keyed by id (UUID string).
        self.owners = {}
        self.pets = {}
        self.vaccination_records = {}
        self.kennels = {}
        self.licenses = {}
        self.tags = {}
        self.dangerous_dog_cases = {}
        self.lost_found_reports = {}
        self.audit_events = {}

        # Monotonic tag serial counter (PRD §3.4: serial in monotonic issuance order).
        self._tag_serial_seq = 0

        # Logical "current time" (PRD §2.10). Defaults to real now until set;
        # tests set it explicitly via /_clock/set before any temporal logic.
        self.current_utc = datetime.now(timezone.utc)

    def next_tag_serial(self):
        self._tag_serial_seq += 1
        return "TAG-{:06d}".format(self._tag_serial_seq)


db = DB()


def reset():
    """Re-initialise the store. Used only at process boot for total cleanliness."""
    global db
    db = DB()


# --------------------------------------------------------------------------- #
# id / timestamp helpers
# --------------------------------------------------------------------------- #
def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    return iso(db.current_utc)


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)
