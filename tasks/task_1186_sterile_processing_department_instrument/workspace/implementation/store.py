"""In-memory data store. Starts EMPTY on every boot — nothing is seeded."""
import itertools

from common import ApiError, logical_now, new_id

_SEQ = itertools.count(1)

TRAY_TEMPLATES = {}
TRAYS = {}
ASSEMBLY_VERIFICATIONS = {}
INSTRUMENTS = {}
REPAIR_ORDERS = {}
STERILIZERS = {}
STERILIZATION_LOADS = {}
BIOLOGICAL_INDICATORS = {}
OR_CASES = {}
TRAY_RESERVATIONS = {}
IUSS_EXCEPTIONS = {}
TECHNICIANS = {}
LOANER_SETS = {}

# Competency demerit events: {"technician_id", "points", "at" (datetime)}.
COMPETENCY_EVENTS = []


def fetch(table, resource_id):
    """Resolve a path id, raising ERR_NOT_FOUND when it does not resolve."""
    if not isinstance(resource_id, str) or resource_id not in table:
        raise ApiError("ERR_NOT_FOUND", 404,
                       "The requested resource does not exist.")
    return table[resource_id]


def new_record(with_version=True):
    """Common system fields. created_at/updated_at read the logical clock."""
    now = logical_now()
    record = {
        "id": new_id(),
        "created_at": now,
        "_seq": next(_SEQ),
    }
    if with_version:
        record["updated_at"] = now
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version on a mutation."""
    if "version" in record:
        record["updated_at"] = logical_now()
        record["version"] = record["version"] + 1
    return record


def ordered(rows):
    """List ordering: created_at ascending, stable by insertion sequence."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
