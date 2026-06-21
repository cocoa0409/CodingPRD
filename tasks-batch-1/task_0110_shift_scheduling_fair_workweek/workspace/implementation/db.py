"""In-memory data store (PRD §2.4).

All state lives in module-level dicts keyed by id. The store starts EMPTY on
every boot — no seeding, no preload. start.sh re-invocation wipes everything
because the process restarts.

Common-field resources carry id, created_at, updated_at, version.
PredictabilityLedgerEntry is append-only: id + created_at only.
"""
import itertools
import uuid
from datetime import datetime, timezone

# Collections keyed by id.
locations = {}
workers = {}
availabilities = {}
time_off_requests = {}
shift_templates = {}
shifts = {}
assignments = {}
bids = {}
swaps = {}
ledger = {}
pay_periods = {}

# Monotonic creation sequence: stable tie-break for "created_at ASC" sorting
# when two records share an identical wall-clock timestamp.
_seq = itertools.count(1)


def reset():
    for d in (locations, workers, availabilities, time_off_requests,
              shift_templates, shifts, assignments, bids, swaps, ledger,
              pay_periods):
        d.clear()
    global _seq
    _seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def _wall_now():
    return datetime.now(timezone.utc)


def iso_millis(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def common_fields():
    """Fresh id + created_at/updated_at + version for a mutable resource."""
    ts = _wall_now()
    iso = iso_millis(ts)
    return {
        "id": new_id(),
        "created_at": iso,
        "updated_at": iso,
        "version": 1,
        "_seq": next(_seq),  # internal: stable creation ordering, stripped on output
    }


def ledger_fields():
    """id + created_at only (append-only event)."""
    ts = _wall_now()
    return {
        "id": new_id(),
        "created_at": iso_millis(ts),
        "_seq": next(_seq),
    }


def touch(record):
    """Mark a mutable resource changed: bump updated_at and version (PRD §2.4)."""
    record["updated_at"] = iso_millis(_wall_now())
    record["version"] = record["version"] + 1
