"""In-memory store, logical clock, and audit-field helpers.

The store is process-local and starts completely empty on every boot: no
seeding, no preloading, no persistence of any kind.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g

# --------------------------------------------------------------------------
# rounding
# --------------------------------------------------------------------------

TWO = Decimal("0.01")
FOUR = Decimal("0.0001")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round2(value):
    return dec(value).quantize(TWO, rounding=ROUND_HALF_UP)


def round4(value):
    return dec(value).quantize(FOUR, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

INITIAL_CLOCK_RAW = "2026-08-01T00:00:00Z"
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.control_requirements = {}
        self.insured_accounts = {}
        self.applications = {}
        self.control_attestations = {}
        self.external_scans = {}
        self.policies = {}
        self.coverage_sections = {}
        self.panel_vendors = {}
        self.incident_claims = {}
        self.vendor_engagements = {}
        self.proofs_of_loss = {}
        self.claim_payments = {}
        self.renewal_assessments = {}
        self.systemic_scenarios = {}
        self.clock = INITIAL_CLOCK
        self.clock_raw = INITIAL_CLOCK_RAW
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def now_dt():
    return store.clock


def iso3(moment):
    moment = moment.astimezone(timezone.utc)
    return "%s.%03dZ" % (moment.strftime("%Y-%m-%dT%H:%M:%S"), moment.microsecond // 1000)


def now_iso():
    return iso3(store.clock)


def plus_days(moment, days):
    return moment + timedelta(days=days)


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def new_row(fields, common=True):
    """Build a row dict with system-managed identity/audit fields."""
    row = {"id": new_id(), "created_at": now_iso()}
    if common:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row.update(fields)
    row["_seq"] = store.next_seq()
    return row


def _touched_set():
    marks = getattr(g, "touched_rows", None)
    if marks is None:
        marks = set()
        g.touched_rows = marks
    return marks


def touch(row):
    """Refresh updated_at and bump version -- at most once per request per row."""
    if "version" not in row:
        return row
    marks = _touched_set()
    if row["id"] in marks:
        return row
    marks.add(row["id"])
    row["updated_at"] = now_iso()
    row["version"] = row["version"] + 1
    return row


# --------------------------------------------------------------------------
# ordering helpers
# --------------------------------------------------------------------------

def by_created(row):
    return (row["created_at"], row["_seq"])


def sorted_by_created(rows):
    return sorted(rows, key=by_created)


def public(row):
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))
