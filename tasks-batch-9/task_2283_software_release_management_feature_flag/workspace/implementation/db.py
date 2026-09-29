"""In-memory data store and logical clock.

Storage is process-local Python dicts keyed by id.  Nothing is persisted and
nothing is seeded: the store starts completely empty on every boot.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from errors import fail

# PRD 2.4: the logical clock reads exactly this on startup and never advances
# on its own, and never falls back to host wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "release_trains",
    "environments",
    "releases",
    "change_requests",
    "change_dependencies",
    "approvals",
    "feature_flags",
    "change_flag_links",
    "flag_rollout_steps",
    "deployments",
    "canary_evaluations",
    "health_signals",
    "incidents",
    "release_notes",
    "evidence_packets",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


# --------------------------------------------------------------------------
# clock / ids / timestamps
# --------------------------------------------------------------------------
def now():
    return store.clock


def set_clock(dt):
    store.clock = dt
    return store.clock


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant; returns an aware UTC datetime or raises ValueError."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not a timestamp")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def num(value):
    """Normalise a computed numeric so integral values serialise as integers."""
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float):
        if value == int(value):
            return int(value)
        return value
    return value


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------
def make(collection, fields, common=True):
    """Create a record.  `common=False` produces an append-only audit row
    carrying only id and created_at (PRD 2.5)."""
    rec = {"id": new_id()}
    rec.update(fields)
    rec["created_at"] = now()
    if common:
        rec["updated_at"] = now()
        rec["version"] = 1
    rec["_seq"] = store.next_seq()
    getattr(store, collection)[rec["id"]] = rec
    return rec


def touch(rec):
    """Refresh updated_at and bump version (governed resources only)."""
    if "version" in rec:
        rec["updated_at"] = now()
        rec["version"] += 1


def upd(rec, **fields):
    """Apply field values; refresh updated_at / version only if something
    actually changed (PRD 2.10: a mutation is a real change)."""
    changed = False
    for key, value in fields.items():
        if rec.get(key) != value or key not in rec:
            rec[key] = value
            changed = True
    if changed:
        touch(rec)
    return changed


def public(rec):
    """Serialise a record, dropping private bookkeeping keys."""
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = iso(value)
        elif isinstance(value, Decimal):
            out[key] = num(value)
        else:
            out[key] = value
    return out


def by_creation(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def latest(records):
    """Latest-created record (created_at then insertion order)."""
    ordered = by_creation(records)
    return ordered[-1] if ordered else None


# --------------------------------------------------------------------------
# path lookups (each reports its own not-found error, PRD 2.8 rank 4)
# --------------------------------------------------------------------------
def get_train(train_id):
    rec = store.release_trains.get(train_id)
    if rec is None:
        fail("ERR_RELEASE_TRAIN_NOT_FOUND", "Release train %s not found" % train_id)
    return rec


def get_release(release_id):
    rec = store.releases.get(release_id)
    if rec is None:
        fail("ERR_RELEASE_NOT_FOUND", "Release %s not found" % release_id)
    return rec


def get_change(change_id):
    rec = store.change_requests.get(change_id)
    if rec is None:
        fail("ERR_CHANGE_REQUEST_NOT_FOUND", "Change request %s not found" % change_id)
    return rec


def get_flag(flag_id):
    rec = store.feature_flags.get(flag_id)
    if rec is None:
        fail("ERR_FEATURE_FLAG_NOT_FOUND", "Feature flag %s not found" % flag_id)
    return rec


def get_step(step_id):
    rec = store.flag_rollout_steps.get(step_id)
    if rec is None:
        fail("ERR_ROLLOUT_STEP_NOT_FOUND", "Rollout step %s not found" % step_id)
    return rec


def get_deployment(deployment_id):
    rec = store.deployments.get(deployment_id)
    if rec is None:
        fail("ERR_DEPLOYMENT_NOT_FOUND", "Deployment %s not found" % deployment_id)
    return rec


def get_environment(environment_id):
    rec = store.environments.get(environment_id)
    if rec is None:
        fail("ERR_RESOURCE_NOT_FOUND", "Environment %s not found" % environment_id)
    return rec


def get_incident(incident_id):
    rec = store.incidents.get(incident_id)
    if rec is None:
        fail("ERR_RESOURCE_NOT_FOUND", "Incident %s not found" % incident_id)
    return rec


def get_note(note_id):
    rec = store.release_notes.get(note_id)
    if rec is None:
        fail("ERR_RESOURCE_NOT_FOUND", "Release note document %s not found" % note_id)
    return rec


def get_packet(packet_id):
    rec = store.evidence_packets.get(packet_id)
    if rec is None:
        fail("ERR_RESOURCE_NOT_FOUND", "Evidence packet %s not found" % packet_id)
    return rec


# --------------------------------------------------------------------------
# reverse-reachability helpers
# --------------------------------------------------------------------------
def releases_of_train(train_id):
    return [r for r in store.releases.values() if r["release_train_id"] == train_id]


def changes_of_release(release_id):
    return [c for c in store.change_requests.values() if c["release_id"] == release_id]


def approvals_of_change(change_id):
    return [a for a in store.approvals.values() if a["change_request_id"] == change_id]


def deps_from(change_id):
    return [d for d in store.change_dependencies.values() if d["from_change_id"] == change_id]


def deps_to(change_id):
    return [d for d in store.change_dependencies.values() if d["to_change_id"] == change_id]


def links_of_change(change_id):
    return [l for l in store.change_flag_links.values() if l["change_request_id"] == change_id]


def links_of_flag(flag_id):
    return [l for l in store.change_flag_links.values() if l["feature_flag_id"] == flag_id]


def steps_of_flag(flag_id):
    return [s for s in store.flag_rollout_steps.values() if s["feature_flag_id"] == flag_id]


def steps_of_deployment(deployment_id):
    return [
        s
        for s in store.flag_rollout_steps.values()
        if s.get("deployment_id") == deployment_id
    ]


def deployments_of_release(release_id):
    return [d for d in store.deployments.values() if d["release_id"] == release_id]


def deployments_of_environment(environment_id):
    return [d for d in store.deployments.values() if d["environment_id"] == environment_id]


def signals_of_deployment(deployment_id):
    return [h for h in store.health_signals.values() if h["deployment_id"] == deployment_id]


def evaluations_of_deployment(deployment_id):
    return [
        e for e in store.canary_evaluations.values() if e["deployment_id"] == deployment_id
    ]


def notes_of_release(release_id):
    return [n for n in store.release_notes.values() if n["release_id"] == release_id]


def packets_of_release(release_id):
    return [p for p in store.evidence_packets.values() if p["release_id"] == release_id]
