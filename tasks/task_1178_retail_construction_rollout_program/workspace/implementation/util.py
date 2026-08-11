"""Timestamps, ids, parsing, and entity plumbing (PRD §2.4, §2.6)."""
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from flask import g, has_request_context

import clock


def new_id():
    return str(uuid.uuid4())


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def iso_dt(dt):
    """ISO 8601 UTC, seconds precision."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp_now():
    return iso_ms(clock.now())


def parse_datetime(value):
    """Lenient ISO 8601 datetime parse -> naive UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if not s:
        raise ValueError("empty")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return datetime.strptime(s, "%Y-%m-%d")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_date(value):
    """Lenient ISO date parse -> datetime.date. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return date.fromisoformat(s)
    return parse_datetime(s).date()


def new_entity(store):
    """Common resource properties (§2.4): id, created_at, updated_at, version."""
    ts = stamp_now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def _bump_registry():
    """Request-scoped set of already-bumped entity ids: a single request that
    mutates one resource through several cascades still increments its version
    exactly once (§2.4 — one mutation event per request per resource)."""
    if not has_request_context():
        return None
    if not hasattr(g, "_bumped_ids"):
        g._bumped_ids = set()
    return g._bumped_ids


def bump(entity):
    registry = _bump_registry()
    if registry is not None:
        if entity["id"] in registry:
            return
        registry.add(entity["id"])
    entity["version"] += 1
    entity["updated_at"] = stamp_now()


def apply_changes(entity, changes):
    """Set fields; bump only if some value actually changed. Returns changed."""
    changed = False
    for k, v in changes.items():
        if entity.get(k) != v:
            entity[k] = v
            changed = True
    if changed:
        bump(entity)
    return changed


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sort_key(entity):
    return (entity["created_at"], entity["_seq"])


def daterange_days(start, end):
    """Whole days in half-open [start, end)."""
    return max(0, (end - start).days)
