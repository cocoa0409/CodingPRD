"""In-memory data store for the Material Testing Lab API.

All tables are dicts keyed by id (a UUID v4 string with no type prefix).
Append-only tables (audit events, data modifications, instrument bookings)
also live here for uniformity.
"""

import uuid
import threading

# A coarse global lock so concurrent writes serialise to a single thread of
# truth. Flask's dev server is single-threaded by default but tests may use
# threaded mode, and the spec explicitly calls out first-writer-wins races.
LOCK = threading.RLock()


def new_id():
    return str(uuid.uuid4())


DB = {
    "clients": {},               # id -> Client
    "testers": {},               # id -> Tester
    "reviewers": {},             # id -> Reviewer
    "signatories": {},           # id -> Signatory
    "instruments": {},           # id -> Instrument
    "samples": {},               # id -> Sample
    "tasks": {},                 # id -> TestTask
    "bookings": {},              # id -> InstrumentBooking
    "records": {},               # id -> TestRecord
    "modifications": [],         # list of DataModification (append-only)
    "reports": {},               # id -> Report
    "invoices": {},              # id -> Invoice
    "audit_events": [],          # list (append-only)
    "sample_code_seq": {},       # (material_category, yyyymmdd) -> int
    "storage_bin_seq": {},       # material_category -> int (next NN)
    "priority_seq": 0,           # task ordering counter
    "internal_audit_dates": set(),   # UTC date strings already audited today
    "accreditation_categories": None,  # accreditation snapshot (or None)
}


def reset():
    DB["clients"] = {}
    DB["testers"] = {}
    DB["reviewers"] = {}
    DB["signatories"] = {}
    DB["instruments"] = {}
    DB["samples"] = {}
    DB["tasks"] = {}
    DB["bookings"] = {}
    DB["records"] = {}
    DB["modifications"] = []
    DB["reports"] = {}
    DB["invoices"] = {}
    DB["audit_events"] = []
    DB["sample_code_seq"] = {}
    DB["storage_bin_seq"] = {}
    DB["priority_seq"] = 0
    DB["internal_audit_dates"] = set()
    DB["accreditation_categories"] = None


def next_priority_seq():
    DB["priority_seq"] += 1
    return DB["priority_seq"]


def next_sample_seq(material_category: str, yyyymmdd: str) -> int:
    key = (material_category, yyyymmdd)
    cur = DB["sample_code_seq"].get(key, 0) + 1
    DB["sample_code_seq"][key] = cur
    return cur


def next_storage_bin(material_category: str) -> int:
    cur = DB["storage_bin_seq"].get(material_category, 0) + 1
    DB["storage_bin_seq"][material_category] = cur
    return cur
