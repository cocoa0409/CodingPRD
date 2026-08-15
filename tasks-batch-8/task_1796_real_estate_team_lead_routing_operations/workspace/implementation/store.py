"""In-memory data store. Starts completely empty on every boot — no seeding."""
from datetime import datetime, timezone
import itertools

# Entity tables: id -> record (plain dicts)
teams = {}
agents = {}
timeoffs = {}
policies = {}
sources = {}
leads = {}
assignments = {}
events = {}
campaigns = {}
enrollments = {}
partners = {}
agreements = {}
deals = {}

# Logical clock: never falls back to wall-clock time.
clock = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}

# Per-team monotonically increasing rotation sequence (team_id -> last value).
rotation_seq = {}

# Global insertion sequence for stable created_at tie-breaking.
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def next_rotation(team_id):
    rotation_seq[team_id] = rotation_seq.get(team_id, 0) + 1
    return rotation_seq[team_id]


def now():
    return clock["now"]


def touch(rec):
    """Every mutation refreshes updated_at and bumps version."""
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 1) + 1
