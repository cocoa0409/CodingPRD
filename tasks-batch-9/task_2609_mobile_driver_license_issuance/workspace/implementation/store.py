"""In-memory store, logical clock and row plumbing.

Every byte of state lives in this process only: plain dicts keyed by id.
Nothing is seeded -- a freshly started server holds no entities at all.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

ROLES = (
    "SystemAdmin",
    "ProofingAgent",
    "CredentialAdjudicator",
    "Holder",
    "VerifierOperator",
    "PrivacyAuditor",
)

COLLECTIONS = (
    "interop_profiles",
    "holders",
    "proofing_sessions",
    "evidence",
    "devices",
    "credentials",
    "update_orders",
    "deliveries",
    "revocation_entries",
    "verifiers",
    "reader_apps",
    "snapshots",
    "presentation_sessions",
    "log_entries",
)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------------------
# clock helpers
# --------------------------------------------------------------------------
def now():
    return db.clock


def set_clock(value):
    db.clock = value


def new_id():
    return str(uuid.uuid4())


def days(n):
    return timedelta(days=n)


def iso(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------
def base_row(kind, common_fields=True):
    row = {
        "id": new_id(),
        "created_at": now(),
        "_kind": kind,
        "_seq": db.next_seq(),
    }
    if common_fields:
        row["updated_at"] = now()
        row["version"] = 1
    return row


def touch(row, bump_version=True):
    """Refresh updated_at; bump version at most once per HTTP request."""
    if row is None or "updated_at" not in row:
        return
    row["updated_at"] = now()
    if not bump_version or "version" not in row:
        return
    try:
        touched = g._mdl_touched
    except (AttributeError, RuntimeError):
        touched = None
    if touched is None:
        try:
            touched = set()
            g._mdl_touched = touched
        except RuntimeError:
            row["version"] += 1
            return
    if row["id"] not in touched:
        touched.add(row["id"])
        row["version"] += 1


def sort_rows(rows, key="created_at"):
    return sorted(rows, key=lambda r: (r.get(key), r["_seq"]))


def values(collection):
    return list(collection.values())


# --------------------------------------------------------------------------
# the active interoperability profile
# --------------------------------------------------------------------------
PROFILE_FALLBACK = {
    "required_assurance_level": "IAL2",
    "max_devices_per_holder": 2,
    "max_active_credentials_per_holder": 2,
    "proofing_validity_days": 180,
    "revocation_freshness_seconds": 300,
    "age_only_allowed_elements": ["age_over_18", "age_over_21", "portrait"],
    "standard_version": None,
    "pending_republish_count": 0,
    "is_active": True,
}


def active_profile_row():
    """The persisted profile currently governing issuance, or None."""
    candidates = [p for p in db.interop_profiles.values() if p.get("is_active")]
    if not candidates:
        candidates = list(db.interop_profiles.values())
    if not candidates:
        return None
    return sort_rows(candidates)[-1]


def profile_settings():
    """Governing settings; jurisdiction defaults when no profile exists yet."""
    row = active_profile_row()
    if row is None:
        return dict(PROFILE_FALLBACK)
    return row


def newest_snapshot(profile_row):
    if profile_row is None:
        return None
    snaps = [
        s for s in db.snapshots.values() if s["interop_profile_id"] == profile_row["id"]
    ]
    if not snaps:
        return None
    return sorted(snaps, key=lambda s: s["snapshot_sequence"])[-1]
