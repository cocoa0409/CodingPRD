"""In-memory data store. Everything resets on process restart."""
import itertools
import threading

_lock = threading.Lock()

# entity dicts keyed by id
customers = {}
pricing_agreements = {}
raw_material_lots = {}
recipes = {}
tanks = {}
cleaning_records = {}
batch_jobs = {}
batch_charges = {}
sds_documents = {}
package_configs = {}
shipments = {}
heel_disposals = {}

# Logical clock state (ISO8601 string); default per PRD §2.5
_clock_state = {"current_utc": "2026-08-01T00:00:00Z"}

_request_counter = itertools.count(1)


def next_request_id():
    n = next(_request_counter)
    return f"req_{n:024d}"


def get_clock():
    return _clock_state["current_utc"]


def set_clock(iso):
    _clock_state["current_utc"] = iso
