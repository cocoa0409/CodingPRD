"""In-memory data store.

The store starts completely empty on every boot.  Nothing is seeded, preloaded
or hardcoded: every row is created by a client through a declared endpoint.
"""
import copy
import itertools
import uuid
from datetime import datetime

from flask import g

from dt_util import fmt_datetime, utc_now

DEFAULT_CLOCK_RAW = '2026-08-01T00:00:00Z'
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0)

COLLECTIONS = (
    'accounts',
    'csms',
    'coverage_assignments',
    'account_signals',
    'sponsor_contacts',
    'executive_engagements',
    'outcome_goals',
    'onboarding_milestones',
    'save_plays',
    'escalation_cases',
    'remediation_commitments',
    'renewal_forecasts',
    'expansion_opportunities',
    'advocacy_enrollments',
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self.clock_raw = DEFAULT_CLOCK_RAW
        self._seq = itertools.count(1)

    # ---- logical clock -------------------------------------------------
    def now(self):
        """The logical clock.  Nothing in this service reads the wall clock for
        windows, sweeps or date arithmetic."""
        return self.clock

    def today(self):
        return self.clock.date()

    def clock_stamp(self):
        return fmt_datetime(self.clock)

    def set_clock(self, dt, raw):
        self.clock = dt
        self.clock_raw = raw

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def wall_stamp():
    return fmt_datetime(utc_now())


def base_row(versioned=True):
    """Common system fields.  ``versioned`` is False for AccountSignal, which
    carries only ``id`` and ``created_at``."""
    stamp = wall_stamp()
    row = {'id': new_id(), 'created_at': stamp, '_seq': db.next_seq()}
    if versioned:
        row['updated_at'] = stamp
        row['version'] = 1
    return row


# ---------------------------------------------------------------------------
# Change tracking.  A write endpoint bumps ``version`` by exactly one and
# refreshes ``updated_at`` for every row it mutates, including rows the server
# touches on its own initiative through a cascade.
# ---------------------------------------------------------------------------

_IGNORED = ('updated_at', 'version', '_seq')


def _registry():
    if not hasattr(g, '_tracked_rows'):
        g._tracked_rows = {}
        g._forced_rows = set()
        g._fresh_rows = set()
    return g._tracked_rows


def _snapshot(row):
    return copy.deepcopy({k: v for k, v in row.items() if k not in _IGNORED})


def mark_fresh(row):
    """Rows created by the current request never get a version bump."""
    _registry()
    g._fresh_rows.add(row['id'])


def track(row):
    """Register a row for change detection before mutating it."""
    if row is None or 'version' not in row:
        return
    reg = _registry()
    if row['id'] in g._fresh_rows:
        return
    if row['id'] not in reg:
        reg[row['id']] = (row, _snapshot(row))


def touch(row):
    """Register a row that must be bumped whether or not a value changed."""
    if row is None or 'version' not in row:
        return
    track(row)
    if row['id'] not in g._fresh_rows:
        g._forced_rows.add(row['id'])


def commit():
    """Apply version / updated_at bumps for everything mutated this request."""
    reg = _registry()
    if not reg:
        return
    stamp = wall_stamp()
    for row_id, (row, before) in list(reg.items()):
        if row_id in g._forced_rows or _snapshot(row) != before:
            row['version'] = row['version'] + 1
            row['updated_at'] = stamp
    reg.clear()
    g._forced_rows.clear()


# ---------------------------------------------------------------------------
# Ordered collection access.  Default ordering everywhere is created_at
# ascending; the monotonic insertion sequence breaks exact ties.
# ---------------------------------------------------------------------------

def ordered(collection):
    return sorted(collection.values(), key=lambda r: (r['created_at'], r['_seq']))


def account_signals(account_id, kind=None):
    rows = [r for r in ordered(db.account_signals) if r['account_id'] == account_id]
    if kind is not None:
        rows = [r for r in rows if r['signal_kind'] == kind]
    return rows


def account_sponsors(account_id):
    return [r for r in ordered(db.sponsor_contacts) if r['account_id'] == account_id]


def account_engagements(account_id):
    return [r for r in ordered(db.executive_engagements)
            if r['account_id'] == account_id]


def sponsor_engagements(sponsor_contact_id):
    return [r for r in ordered(db.executive_engagements)
            if r['sponsor_contact_id'] == sponsor_contact_id]


def account_goals(account_id):
    return [r for r in ordered(db.outcome_goals) if r['account_id'] == account_id]


def account_milestones(account_id):
    return [r for r in ordered(db.onboarding_milestones)
            if r['account_id'] == account_id]


def account_assignments(account_id):
    return [r for r in ordered(db.coverage_assignments)
            if r['account_id'] == account_id]


def csm_assignments(csm_id):
    return [r for r in ordered(db.coverage_assignments) if r['csm_id'] == csm_id]


def account_save_plays(account_id):
    return [r for r in ordered(db.save_plays) if r['account_id'] == account_id]


def account_escalations(account_id):
    return [r for r in ordered(db.escalation_cases) if r['account_id'] == account_id]


def save_play_escalations(save_play_id):
    return [r for r in ordered(db.escalation_cases)
            if r['save_play_id'] == save_play_id]


def case_commitments(escalation_case_id):
    return [r for r in ordered(db.remediation_commitments)
            if r['escalation_case_id'] == escalation_case_id]


def account_forecasts(account_id):
    return [r for r in ordered(db.renewal_forecasts) if r['account_id'] == account_id]


def account_opportunities(account_id):
    return [r for r in ordered(db.expansion_opportunities)
            if r['account_id'] == account_id]


def account_enrollments(account_id):
    return [r for r in ordered(db.advocacy_enrollments)
            if r['account_id'] == account_id]
