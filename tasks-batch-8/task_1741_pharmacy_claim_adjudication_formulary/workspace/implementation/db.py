import itertools
import uuid

from response import now_ts

# In-memory stores. The store starts EMPTY on every boot — no seeding.
plans = {}
drugs = {}
formulary_entries = {}
pharmacies = {}
members = {}
prior_authorizations = {}
claims = {}
dur_alerts = {}
audits = {}

_seq_counter = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def base_record():
    """Common system-managed fields for primary resources."""
    ts = now_ts()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(_seq_counter),
    }


def touch(rec):
    """Every mutation refreshes updated_at and increments version."""
    rec["version"] += 1
    rec["updated_at"] = now_ts()


def public(rec):
    """Strip internal bookkeeping fields from a stored record."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sorted_records(records):
    """List endpoints sort by created_at ascending (insertion-order tiebreak)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
