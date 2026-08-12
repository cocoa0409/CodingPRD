"""In-memory data store and logical clock. State is wiped on every process boot."""
import threading
import uuid
from datetime import datetime, timezone

store = {
    "program_years": {},
    "farms": {},
    "documents": {},
    "products": {},
    "offerings": {},
    "forecast_lines": {},
    "kitchens": {},
    "windows": {},
    "agreements": {},
    "amendments": {},
    "deliveries": {},
    "invoices": {},
    "claims": {},
    "claim_lines": {},
    "substitutions": {},
}

_DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": _DEFAULT_CLOCK}
_seq = [0]
_lock = threading.Lock()


def clock_now():
    return _clock["now"]


def clock_date():
    return _clock["now"].date()


def set_clock(dt):
    _clock["now"] = dt


def next_seq():
    with _lock:
        _seq[0] += 1
        return _seq[0]


def iso8601(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso8601(_clock["now"])


def new_record():
    ts = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
