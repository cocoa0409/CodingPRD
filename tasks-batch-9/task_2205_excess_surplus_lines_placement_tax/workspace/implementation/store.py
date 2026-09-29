"""In-memory data store.

Everything lives in plain dicts keyed by id. Nothing is persisted anywhere and
NOTHING is seeded: a freshly booted process holds zero entities of every type.
The only startup state is the logical clock (see clock.py).
"""

import itertools
import uuid

import clock

COLLECTIONS = (
    "brokers",
    "broker_licenses",
    "state_programs",
    "carriers",
    "carrier_eligibilities",
    "market_security_reviews",
    "placements",
    "declinations",
    "policies",
    "policy_state_allocations",
    "endorsements",
    "cancellations",
    "tax_filing_lines",
    "filing_batches",
    "affidavits",
)


class Store(object):
    def __init__(self):
        self._seq = itertools.count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})

    # -- lifecycle ---------------------------------------------------------
    def next_seq(self):
        return next(self._seq)

    def insert(self, collection, fields):
        rec = dict(fields)
        rec["id"] = str(uuid.uuid4())
        stamp = clock.now_iso()
        rec["created_at"] = stamp
        rec["updated_at"] = stamp
        rec["version"] = 1
        rec["_seq"] = self.next_seq()
        getattr(self, collection)[rec["id"]] = rec
        return rec

    def get(self, collection, rec_id):
        if not isinstance(rec_id, str):
            return None
        return getattr(self, collection).get(rec_id)

    def all(self, collection):
        return sort_records(getattr(self, collection).values())


db = Store()


def touch(rec):
    """Record a mutation: bump version, refresh updated_at (PRD 2.5)."""
    rec["version"] = int(rec.get("version", 0)) + 1
    rec["updated_at"] = clock.now_iso()
    return rec


def sort_records(rows):
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def where(collection, **filters):
    rows = []
    for rec in getattr(db, collection).values():
        keep = True
        for key, value in filters.items():
            if value is None:
                continue
            if rec.get(key) != value:
                keep = False
                break
        if keep:
            rows.append(rec)
    return sort_records(rows)


# -- domain-specific lookups ----------------------------------------------

def state_program_by_code(state_code):
    for rec in db.state_programs.values():
        if rec.get("state_code") == state_code:
            return rec
    return None


def carrier_by_naic(naic_number):
    for rec in db.carriers.values():
        if rec.get("naic_number") == naic_number:
            return rec
    return None


def policy_by_number(policy_number):
    for rec in db.policies.values():
        if rec.get("policy_number") == policy_number:
            return rec
    return None


def allocations_of(policy_id):
    rows = [r for r in db.policy_state_allocations.values()
            if r.get("policy_id") == policy_id]
    return sorted(rows, key=lambda r: r.get("state_code") or "")


def endorsements_of(policy_id):
    return sort_records([r for r in db.endorsements.values()
                         if r.get("policy_id") == policy_id])


def declinations_of(placement_id):
    return sort_records([r for r in db.declinations.values()
                         if r.get("placement_id") == placement_id])


def policies_of_placement(placement_id):
    return sort_records([r for r in db.policies.values()
                         if r.get("placement_id") == placement_id])


def lines_of_policy(policy_id):
    return sort_records([r for r in db.tax_filing_lines.values()
                         if r.get("policy_id") == policy_id])


def lines_of_batch(batch_id):
    return sort_records([r for r in db.tax_filing_lines.values()
                         if r.get("filing_batch_id") == batch_id])


def lines_of_endorsement(endorsement_id):
    return sort_records([r for r in db.tax_filing_lines.values()
                         if r.get("source_endorsement_id") == endorsement_id])


def eligibilities_of(carrier_id, state_program_id=None):
    rows = [r for r in db.carrier_eligibilities.values()
            if r.get("carrier_id") == carrier_id
            and (state_program_id is None
                 or r.get("state_program_id") == state_program_id)]
    return sort_records(rows)


def reviews_of_carrier(carrier_id):
    return sort_records([r for r in db.market_security_reviews.values()
                         if r.get("carrier_id") == carrier_id])


def licenses_of_broker(broker_id):
    return sort_records([r for r in db.broker_licenses.values()
                         if r.get("broker_id") == broker_id])
