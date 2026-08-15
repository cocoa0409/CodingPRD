"""In-memory data store and logical clock. Empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

store = {
    "tax_years": {},
    "vendors": {},
    "w9_submissions": {},
    "payments": {},
    "withholding_entries": {},
    "remittances": {},
    "returns": {},
    "transmittals": {},
    "state_rules": {},
    "state_obligations": {},
    "b_notices": {},
    "merge_requests": {},
}

_clock = {"now": DEFAULT_CLOCK}
_seq = {"n": 0}


def logical_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def make_record(kind, fields):
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    now = logical_now()
    rec["created_at"] = fmt_ts(now)
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_created"] = now
    rec["_seq"] = next_seq()
    store[kind][rec["id"]] = rec
    return rec


def make_entry(fields):
    """WithholdingEntry: immutable ledger row with only id + created_at."""
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    now = logical_now()
    rec["created_at"] = fmt_ts(now)
    rec["_created"] = now
    rec["_seq"] = next_seq()
    store["withholding_entries"][rec["id"]] = rec
    return rec


def touch(rec):
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = fmt_ts(logical_now())


def get_or_404(kind, rid):
    from errors import ApiError
    rec = store[kind].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found: %s" % rid)
    return rec
