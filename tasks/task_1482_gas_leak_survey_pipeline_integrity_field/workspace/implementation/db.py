"""In-memory data store, logical clock, and low-level helpers.

All state lives in module-level dicts keyed by id. The store starts empty on
every process boot; nothing is seeded. The logical clock defaults to
2026-08-01T00:00:00Z and is only moved by POST /_clock/set_current_utc.
"""
import itertools
import uuid
from datetime import datetime, timezone

STORE = {
    "pipe_segments": {},
    "instruments": {},
    "calibrations": {},
    "survey_routes": {},
    "route_segment_assignments": {},
    "survey_runs": {},
    "leaks": {},
    "repair_orders": {},
    "excavation_permits": {},
    "repair_crews": {},
    "cp_readings": {},
    "compliance_reports": {},
    "risk_model_snapshots": {},
    "regrade_events": {},
    "field_technicians": {},
    "compliance_officers": {},
    "calibration_techs": {},
    "dispatch_coordinators": {},
    "integrity_analysts": {},
}

_SEQ = itertools.count(1)

CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}

# Field names whose values are datetimes (serialized to ISO 8601 millis Z).
DATETIME_FIELDS = {
    "created_at", "updated_at", "calibrated_at", "calibration_due_at",
    "last_surveyed_at", "next_survey_due_at", "started_at", "ended_at",
    "discovered_at", "repair_due_at", "dispatched_at", "completed_at",
    "applied_at", "granted_at", "expires_at", "recorded_at", "generated_at",
    "submitted_at", "triggered_at", "scheduled_window_start",
    "scheduled_window_end", "reporting_period_start", "reporting_period_end",
}


def now():
    return CLOCK["now"]


def set_clock(dt):
    CLOCK["now"] = dt


def new_seq():
    return next(_SEQ)


def make_entity():
    t = now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": new_seq(),
    }


def touch(ent):
    ent["updated_at"] = now()
    ent["version"] += 1


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 string to an aware UTC datetime; None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def serialize(ent, fields):
    out = {}
    for f in fields:
        v = ent.get(f)
        if f in DATETIME_FIELDS:
            out[f] = fmt_dt(v) if v is not None else None
        else:
            out[f] = v
    return out
