"""In-memory data store.

All state is held in plain Python dicts keyed by id. Nothing is persisted to
disk and nothing is seeded at import time — the store starts empty on every
boot, and tests construct all entities via the API.
"""
import itertools
import uuid
from datetime import datetime, timezone

# One dict per entity collection, keyed by id (UUID string, no type prefix).
practices = {}
sliding_scale_tiers = {}
service_packages = {}
consultants = {}
clients = {}
consults = {}
feeding_assessments = {}
weighted_feeds = {}
follow_up_plans = {}
superbills = {}
dme_qualifications = {}
pediatrician_referrals = {}

# Monotonic sequence used only to order records that share a created_at instant,
# preserving a stable creation order for ascending sort.
_seq = itertools.count()


def new_id():
    # id is a UUID with no type prefix (PRD §2.5).
    return str(uuid.uuid4())


def now_iso_millis():
    """ISO 8601 UTC timestamp with three fractional digits, used for created_at /
    updated_at system fields (PRD §2.5)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def next_seq():
    return next(_seq)
