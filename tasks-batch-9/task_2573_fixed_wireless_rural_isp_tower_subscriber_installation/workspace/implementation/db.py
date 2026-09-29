"""In-memory data store.

Everything lives in plain dicts keyed by id.  Nothing is persisted and nothing
is seeded: a fresh process starts with an entirely empty plant, and every
record any caller needs is built through the public API surface.
"""
import datetime as _dt
import threading
import uuid

from util import UTC

# ---------------------------------------------------------------------------
# logical clock (PRD 2.4)
# ---------------------------------------------------------------------------
CLOCK_EPOCH = _dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

lock = threading.RLock()

_state = {
    "clock": CLOCK_EPOCH,
    "seq": 0,
    "intake_sequence": 0,
    "ingest_sequence": 0,
    "account_sequence": 0,
}

# entity stores -------------------------------------------------------------
towers = {}
backhaul_circuits = {}
spectrum_licenses = {}
sectors = {}
interference_coordinations = {}
service_plans = {}
serviceability_requests = {}
capacity_holds = {}
subscribers = {}
install_work_orders = {}
equipment_assignments = {}
usage_records = {}
outage_events = {}
outage_credits = {}

ALL_STORES = (
    towers, backhaul_circuits, spectrum_licenses, sectors,
    interference_coordinations, service_plans, serviceability_requests,
    capacity_holds, subscribers, install_work_orders, equipment_assignments,
    usage_records, outage_events, outage_credits,
)


def now():
    return _state["clock"]


def set_clock(value):
    _state["clock"] = value
    return _state["clock"]


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def next_intake_sequence():
    _state["intake_sequence"] += 1
    return _state["intake_sequence"]


def next_ingest_sequence():
    _state["ingest_sequence"] += 1
    return _state["ingest_sequence"]


def next_account_number():
    _state["account_sequence"] += 1
    return "RB-%06d" % _state["account_sequence"]


def base_record(**fields):
    """Create a record carrying the four common fields of PRD 2.5."""
    stamp = now()
    record = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }
    record.update(fields)
    return record


def touch(record, bump=True):
    """Mark a record mutated: refresh updated_at and step the version."""
    record["updated_at"] = now()
    if bump:
        record["version"] = record.get("version", 1) + 1
    return record


def sort_key(record):
    """Default ordering: created_at ascending, insertion order as tie-break."""
    return (record["created_at"], record["_seq"])


def ordered(records):
    return sorted(records, key=sort_key)
