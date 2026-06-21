"""In-memory data store and helpers. Starts empty on every boot."""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.properties = {}
        self.borrowers = {}
        self.index_rates = {}
        self.helocs = {}
        self.draws = {}
        self.payments = {}
        self.fee_assessments = {}
        self.covenants = {}
        self.default_events = {}
        self.lien_records = {}
        # Logical clock, defaults to real "now" until set
        self.current_utc = datetime.now(timezone.utc)


db = Store()


def reset():
    global db
    db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso(dt=None):
    """ISO 8601 UTC with three fractional digits, trailing Z."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 string into an aware UTC datetime."""
    if s is None:
        return None
    if isinstance(s, datetime):
        dt = s
    else:
        txt = s.strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def stamp_create(obj, with_common=True):
    ts = now_iso()
    obj["id"] = new_id()
    if with_common:
        obj["created_at"] = ts
        obj["updated_at"] = ts
        obj["version"] = 1
    else:
        # DefaultEvent: only id + created_at
        obj["created_at"] = ts
    return obj


def touch(obj):
    """Mutation: refresh updated_at and bump version."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
