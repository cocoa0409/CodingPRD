"""In-memory data store. Starts EMPTY on every boot -- nothing is seeded."""
from util import new_id, now

parcels = {}
wells = {}
water_samples = {}
site_evaluations = {}
system_designs = {}
contractors = {}
construction_permits = {}
inspections = {}
operating_permits = {}
pumping_records = {}
repair_orders = {}
transfer_inspections = {}

# Per-county construction-permit issue sequence (for permit_number minting).
county_permit_sequence = {}

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_record(with_version=True):
    """A fresh record carrying the housekeeping attributes of PRD 2.4."""
    stamp = now()
    rec = {"id": new_id(), "created_at": stamp}
    if with_version:
        rec["updated_at"] = stamp
        rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Refresh updated_at from the logical clock and increment version by 1."""
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 0) + 1
    return rec


def ordered(values):
    """Ascending created_at order; insertion sequence breaks ties."""
    return sorted(values, key=lambda r: (r["created_at"], r["_seq"]))
