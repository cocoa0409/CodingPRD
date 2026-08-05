"""In-memory data store. Fresh (empty) on every process boot. No seeding."""
import itertools

from util import now_iso, parse_dt

# Entity collections (id -> record dict)
households = {}
members = {}
subscriptions = {}
manufacturers = {}
products = {}
recall_notices = {}
recall_matches = {}
claims = {}
claim_documents = {}
resolutions = {}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


# Logical clock
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"
_clock_iso = DEFAULT_CLOCK


def get_clock_iso():
    return _clock_iso


def get_clock():
    return parse_dt(_clock_iso)


def set_clock(iso):
    global _clock_iso
    _clock_iso = iso


def touch(rec):
    """Refresh updated_at and bump version (for common-field entities)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
