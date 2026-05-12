"""In-memory data store. All tables are dicts keyed by id (UUID string).

History-style child rows (custody_events, audit_log) are stored as ordered lists.
"""

import threading
import uuid


_lock = threading.RLock()

# Primary entity tables
lawyers = {}
cases = {}
parties = {}
document_templates = {}
document_drafts = {}
hearings = {}
evidence_rows = {}
time_entries = {}
bills = {}

# Child/append-only tables
custody_events = {}        # id -> CustodyEvent row
evidence_rebuttals = {}    # id -> EvidenceRebuttal row
audit_logs = []            # ordered list (append-only)

# Case-number sequencing per (year, type_code) pair
case_number_seq = {}       # (year:int, type_code:str) -> int


def new_id():
    return str(uuid.uuid4())


def lock():
    return _lock


def reset_all():
    with _lock:
        lawyers.clear()
        cases.clear()
        parties.clear()
        document_templates.clear()
        document_drafts.clear()
        hearings.clear()
        evidence_rows.clear()
        time_entries.clear()
        bills.clear()
        custody_events.clear()
        evidence_rebuttals.clear()
        audit_logs.clear()
        case_number_seq.clear()


def next_case_seq(year, type_code):
    """Atomically allocate the next sequence number for (year, type_code)."""
    with _lock:
        key = (year, type_code)
        next_seq = case_number_seq.get(key, 0) + 1
        case_number_seq[key] = next_seq
        return next_seq
