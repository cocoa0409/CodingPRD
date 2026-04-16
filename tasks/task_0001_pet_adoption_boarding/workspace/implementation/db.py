"""In-memory data store + utility helpers."""

import uuid
import threading
from datetime import datetime, timezone

_lock = threading.RLock()


def new_id() -> str:
    return str(uuid.uuid4())


def now_dt() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    now = now_dt()
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def fmt_dt(dt: datetime) -> str:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.astimezone(timezone.utc) if s.tzinfo else s.replace(tzinfo=timezone.utc)
    if not isinstance(s, str):
        return None
    try:
        # Support trailing Z
        v = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        return None


class Store:
    def __init__(self):
        self.shelters = {}          # id -> dict
        self.animals = {}           # id -> dict
        self.vaccinations = {}      # id -> dict
        self.adopters = {}          # id -> dict
        self.home_visits = {}       # id -> dict
        self.applications = {}      # id -> dict
        self.reservations = {}      # id -> dict
        self.settlements = {}       # id -> dict
        self.incidents = {}         # id -> dict

    def reset(self):
        self.__init__()


store = Store()
lock = _lock
