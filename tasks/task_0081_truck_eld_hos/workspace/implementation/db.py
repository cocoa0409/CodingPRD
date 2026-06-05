"""In-memory data store. Starts EMPTY on every boot — no seeding, no preload.

All state lives in module-level dicts keyed by id. A fresh process import wipes
everything, satisfying per-test-server isolation.
"""
import uuid

# Each store maps id -> dict record.
drivers = {}
vehicles = {}
devices = {}
duty_events = {}
daily_logs = {}
violations = {}
adverse_claims = {}
pc_segments = {}

# Monotonic insertion counter for stable created_at tie-breaks within the same
# millisecond. Not exposed; used as a hidden ordering key.
_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())
