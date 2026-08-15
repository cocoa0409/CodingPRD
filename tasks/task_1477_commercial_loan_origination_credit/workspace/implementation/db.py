"""In-memory data store and logical clock.

The store starts completely empty on every boot. No seeding of any kind.
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.bank_officers = {}
        self.borrowers = {}
        self.loan_applications = {}
        self.financial_statements = {}
        self.policy_exceptions = {}
        self.appraisers = {}
        self.appraisals = {}
        self.committee_sessions = {}
        self.committee_decisions = {}
        self.term_sheets = {}
        self.commitment_letters = {}
        self.document_checklist_items = {}
        self.funding_authorizations = {}
        self.covenants = {}
        self.participations = {}
        self.seq = 0
        # Logical clock: fixed startup instant, never wall-clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


STORE = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    STORE.seq += 1
    return STORE.seq


def now_dt():
    return STORE.clock


def format_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def now_iso():
    return format_dt(STORE.clock)


def new_entity():
    ts = now_iso()
    return {
        'id': new_id(),
        'created_at': ts,
        'updated_at': ts,
        'version': 1,
        '_seq': next_seq(),
    }


def touch(entity):
    entity['updated_at'] = now_iso()
    entity['version'] += 1
