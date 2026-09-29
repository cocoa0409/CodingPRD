"""In-memory store. Nothing is ever seeded: every dict starts empty."""
import itertools
import threading
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.clubs = {}
        self.clinicians = {}
        self.players = {}
        self.games = {}
        self.baseline_tests = {}
        self.sideline_evaluations = {}
        self.concussion_cases = {}
        self.return_steps = {}
        self.inc_clearances = {}
        self.protocol_audits = {}
        self.injury_report_entries = {}
        self.now = DEFAULT_CLOCK
        self._seq = itertools.count(1)
        self.lock = threading.RLock()

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def stamp_new(row):
    """Attach the four system-managed properties to a brand new row."""
    row["id"] = new_id()
    row["created_at"] = db.now
    row["updated_at"] = db.now
    row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Record a mutation: bump version and refresh updated_at."""
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = db.now
    return row


def sort_rows(rows):
    """created_at ASC, stable by insertion sequence."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
