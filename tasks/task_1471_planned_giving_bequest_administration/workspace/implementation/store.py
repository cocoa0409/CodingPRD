"""In-memory data store + logical clock. Store starts empty on every boot.

The only record materialized at startup is the ReserveFund singleton, which
PRD section 2.8 explicitly mandates ('instantiated at server startup with
name CGA_RESERVE, balance_cents equal to zero, and posture SOLVENT').
No other entity is seeded.
"""
import itertools
import uuid
from datetime import datetime, timezone

# Entity tables (dicts keyed by id)
donors = {}
rate_tables = {}
illustrations = {}
agreements = {}
designations = {}
assets = {}
payments = {}
estates = {}
milestones = {}
funds = {}
valuation_runs = {}

# ReserveFund singleton (PRD 2.8)
reserve_fund = None

# Logical clock: starts at exactly 2026-08-01T00:00:00Z, never wall clock.
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_seq = itertools.count(1)


def now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def iso(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def next_seq():
    return next(_seq)


def base_fields():
    t = iso(_clock)
    return {
        "id": str(uuid.uuid4()),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    """Refresh updated_at and bump version (PRD 2.5)."""
    entity["updated_at"] = iso(_clock)
    entity["version"] += 1


def init_reserve_fund():
    global reserve_fund
    reserve_fund = dict(base_fields())
    reserve_fund.update({
        "name": "CGA_RESERVE",
        "balance_cents": 0,
        "booked_target_cents": 0,
        "projected_target_cents": 0,
        "booked_coverage_bps": None,
        "posture": "SOLVENT",
    })
    return reserve_fund
