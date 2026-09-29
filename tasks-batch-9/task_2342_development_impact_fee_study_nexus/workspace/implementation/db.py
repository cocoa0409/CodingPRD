"""In-memory storage. Nothing is ever seeded: every table starts empty."""

import itertools
import threading
from uuid import uuid4

import clock

fee_programs = {}
facility_categories = {}
fee_studies = {}
nexus_components = {}
fee_schedule_items = {}
protest_filings = {}
development_applications = {}
credit_claims = {}
deferral_agreements = {}
fund_ledger_entries = {}

# (fee_program_id, fiscal_year) -> filing record; not an addressable entity.
annual_reports = {}

lock = threading.RLock()

_counter = itertools.count(1)


def next_seq():
    return next(_counter)


def new_record(**fields):
    moment = clock.now()
    record = {
        "id": str(uuid4()),
        "created_at": moment,
        "updated_at": moment,
        "version": 1,
        "_seq": next_seq(),
    }
    record.update(fields)
    return record


def touch(record):
    record["version"] += 1
    record["updated_at"] = clock.now()
    return record


def order_key(record):
    """created_at ASC with insertion order as the tie-break."""
    return (record["created_at"], record["_seq"])


def ordered(table):
    return sorted(table.values(), key=order_key)
