"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts EMPTY on every process boot (per-test-server isolation wipes
state by re-launching start.sh). Nothing is seeded, preloaded, or hardcoded.
"""
import uuid

import clock

# Collections keyed by id (UUID string, no type prefix).
patients = {}
suppliers = {}
hcpcs_items = {}
dme_orders = {}
cmns = {}
prior_authorizations = {}
deliveries = {}
rental_cycles = {}
claim_lines = {}
cpap_resupply_orders = {}
audits = {}


def new_id():
    return str(uuid.uuid4())


def _ts():
    dt = clock.now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def init_common(record):
    """Stamp id/created_at/updated_at/version on a freshly created record."""
    record["id"] = new_id()
    ts = _ts()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """Mutation: refresh updated_at and bump version by 1 (PRD 2.4)."""
    record["updated_at"] = _ts()
    record["version"] = record.get("version", 1) + 1
    return record
