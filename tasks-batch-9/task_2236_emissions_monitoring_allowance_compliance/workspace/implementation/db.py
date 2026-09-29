"""In-memory store.

Every collection is a plain ``dict`` keyed by entity id and starts **empty** on
every boot -- nothing is seeded, preloaded or hardcoded. The logical clock
(PRD 2.4) lives here too; the server never reads the wall clock.

Records also carry underscore-prefixed internal keys (parsed datetimes, an
insertion sequence used as a stable tie-break). :func:`public` strips them.
"""

from datetime import datetime

from util import UTC, fmt_dt, new_id

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.facilities = {}
        self.units = {}
        self.monitoring_systems = {}
        self.daily_calibrations = {}
        self.rata_tests = {}
        self.fuel_samples = {}
        self.operating_hours = {}
        self.quarterly_reports = {}
        self.certifications = {}
        self.permit_limits = {}
        self.excess_events = {}
        self.allowance_accounts = {}
        self.allowance_transactions = {}
        self.control_outages = {}
        self.current_utc = DEFAULT_CLOCK
        self._seq = 0

    # -- logical clock -------------------------------------------------------
    def now(self):
        return self.current_utc

    def now_str(self):
        return fmt_dt(self.current_utc)

    # -- sequencing ----------------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def public(record):
    """Strip internal keys from a record before serialisation."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def public_list(records):
    return [public(r) for r in records]


def base_record(versioned=True):
    """Common system fields (PRD 2.5)."""
    rec = {"id": new_id(), "created_at": db.now_str()}
    if versioned:
        rec["updated_at"] = db.now_str()
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(record):
    """One mutation == updated_at refreshed and version incremented by one."""
    record["updated_at"] = db.now_str()
    record["version"] = record.get("version", 1) + 1


def sort_rows(rows, descending=False):
    """Default ordering is ``created_at`` ascending; ties fall back to the
    insertion sequence so ordering is stable even under a frozen logical clock.
    """
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    if descending:
        ordered.reverse()
    return ordered
