"""In-memory data store, logical clock, id/timestamp helpers.

Storage is process-local dicts keyed by id. The store starts empty on every
boot; nothing is seeded at startup.
"""
import uuid
from datetime import datetime, timedelta, timezone

DEFAULT_NOW = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
HELD_TTL_MINUTES = 15

# ---- stores (empty at boot) ----
clients = {}
engineers = {}
platform_profiles = {}
rush_tier_rules = {}
projects = {}
session_slots = {}
source_assets = {}
revision_rounds = {}
deliverables = {}
qc_reports = {}
metadata_tags = {}
archive_bundles = {}

_seq_counter = [0]


class _Clock:
    def __init__(self):
        self._now = DEFAULT_NOW

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


CLOCK = _Clock()


def now_dt():
    return CLOCK.now()


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '{:03d}Z'.format(dt.microsecond // 1000)


def now_iso():
    return iso(CLOCK.now())


def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError('not a string')
    s = value.strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def on_grid(dt):
    """30-minute boundary: minute :00 or :30, zero seconds/micros."""
    return dt.minute in (0, 30) and dt.second == 0 and dt.microsecond == 0


def new_id():
    return str(uuid.uuid4())


def new_record():
    _seq_counter[0] += 1
    ts = now_iso()
    return {
        'id': new_id(),
        'created_at': ts,
        'updated_at': ts,
        'version': 1,
        '_seq': _seq_counter[0],
    }


def touch(rec):
    rec['updated_at'] = now_iso()
    rec['version'] += 1


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith('_')}


def public_list(recs):
    return [public(r) for r in sorted(recs, key=lambda r: r['_seq'])]
