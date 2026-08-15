"""In-memory data store, logical clock, id and timestamp management.

The store starts EMPTY on every boot. No seeding of any entity.
"""
import threading
import uuid
from datetime import datetime, timezone, timedelta

LOCK = threading.RLock()

STORE = {
    "teams": {},
    "athletes": {},
    "diagnosis_codes": {},
    "injury_cases": {},
    "treatment_plans": {},
    "daily_status_entries": {},
    "rtp_protocols": {},
    "rtp_stage_advances": {},
    "clearances": {},
    "workload_sessions": {},
    "insurance_policies": {},
    "claims": {},
    "disclosure_grants": {},
    "availability_reports": {},
}

CLOCK_DEFAULT_RAW = "2026-08-01T00:00:00Z"
CLOCK = {
    "raw": CLOCK_DEFAULT_RAW,
    "dt": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
}

_last_stamp = None


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now_iso():
    return fmt_ts(datetime.now(timezone.utc))


def clock_dt():
    return CLOCK["dt"]


def clock_date():
    return CLOCK["dt"].date()


def clock_raw():
    return CLOCK["raw"]


def logical_now_iso():
    """Canonical logical timestamp (millis Z)."""
    return fmt_ts(CLOCK["dt"])


def now_stamp():
    """Logical timestamp for created_at/updated_at; strictly monotonic via 1ms bump."""
    global _last_stamp
    base = CLOCK["dt"]
    cand = base
    if _last_stamp is not None and cand <= _last_stamp:
        cand = _last_stamp + timedelta(milliseconds=1)
    _last_stamp = cand
    return fmt_ts(cand)


def stamp_dt(iso):
    """Parse one of our stamped timestamps back to datetime."""
    return parse_iso_dt(iso)


def parse_iso_dt(s):
    if not isinstance(s, str):
        return None
    txt = s.strip()
    try:
        if txt.endswith("Z"):
            dt = datetime.fromisoformat(txt[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def set_clock(raw):
    global _last_stamp
    dt = parse_iso_dt(raw)
    if dt is None:
        return False
    CLOCK["raw"] = raw
    CLOCK["dt"] = dt
    # Every Team.current_utc = raw (verbatim echo on read)
    for team in STORE["teams"].values():
        team["current_utc"] = raw
    return True


def touch(entity):
    entity["updated_at"] = now_stamp()
    entity["version"] = entity.get("version", 1) + 1
