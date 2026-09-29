"""In-memory data store.

Plain Python dicts keyed by the server-minted UUID `id`. The store starts
EMPTY on every boot: nothing is seeded, preloaded or hardcoded here. Every
row is created by a client through one of the declared endpoints.
"""

from common import clock_now, new_id

# BatchOrder.production_status values that hold a claim on a suite and on the
# project's committed-unit ledger (PRD 3.5: "a live batch ... is any batch
# whose production_status is SCHEDULED, SETUP, FILLING or FILLED").
LIVE_PRODUCTION = ("SCHEDULED", "SETUP", "FILLING", "FILLED")


class Store(object):
    def __init__(self):
        self.projects = {}
        self.suites = {}
        self.media_fills = {}
        self.quals = {}
        self.batches = {}
        self.lots = {}
        self.reservations = {}
        self.ipcs = {}
        self.em_samples = {}
        self.deviations = {}
        self.reviews = {}
        self.qp_decisions = {}
        self.engagements = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Store()


# --------------------------------------------------------------------------
# Row construction / mutation
# --------------------------------------------------------------------------


def new_row(fields, versioned=True):
    """Build a row with the common audit stamps (PRD 2.4)."""
    now = clock_now()
    row = {"id": new_id(), "created_at": now, "_seq": DB.next_seq(), "_raw": {}}
    if versioned:
        row["updated_at"] = now
        row["version"] = 1
    row.update(fields)
    return row


def touch(row):
    """One row mutation: version +1 and updated_at refreshed (PRD 2.4/2.6)."""
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = clock_now()
    return row


def set_raw(row, field, raw_value):
    """Remember the client's literal datetime string so reads echo it back."""
    row.setdefault("_raw", {})[field] = raw_value


def by_created(rows):
    """Deterministic created_at ASC ordering.

    The logical clock is frozen between clock calls, so many rows share a
    created_at instant; the internal insertion sequence breaks those ties so
    the ordering is still total and reproducible.
    """
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------
# Collection queries
# --------------------------------------------------------------------------


def batches_of_suite(suite_id):
    return by_created([b for b in DB.batches.values() if b["suite_id"] == suite_id])


def batches_of_project(project_id):
    return by_created(
        [b for b in DB.batches.values() if b["client_project_id"] == project_id]
    )


def live_batches_of_suite(suite_id):
    return [
        b
        for b in batches_of_suite(suite_id)
        if b["production_status"] in LIVE_PRODUCTION
    ]


def reservations_of_batch(batch_id):
    return by_created(
        [r for r in DB.reservations.values() if r["batch_order_id"] == batch_id]
    )


def reservations_of_lot(lot_id):
    return by_created(
        [r for r in DB.reservations.values() if r["component_lot_id"] == lot_id]
    )


def ipcs_of_batch(batch_id):
    return by_created(
        [c for c in DB.ipcs.values() if c["batch_order_id"] == batch_id]
    )


def em_samples_of_suite(suite_id):
    return by_created(
        [s for s in DB.em_samples.values() if s["suite_id"] == suite_id]
    )


def deviations_of_batch(batch_id):
    return by_created(
        [d for d in DB.deviations.values() if d["batch_order_id"] == batch_id]
    )


def deviations_of_sample(sample_id):
    return by_created(
        [d for d in DB.deviations.values() if d["em_sample_id"] == sample_id]
    )


def deviations_of_project(project_id):
    ids = set(b["id"] for b in DB.batches.values() if b["client_project_id"] == project_id)
    return by_created([d for d in DB.deviations.values() if d["batch_order_id"] in ids])


def review_of_batch(batch_id):
    for r in by_created(list(DB.reviews.values())):
        if r["batch_order_id"] == batch_id:
            return r
    return None


def quals_of_suite(suite_id):
    return by_created([q for q in DB.quals.values() if q["suite_id"] == suite_id])


def engagements_of_project(project_id):
    return by_created(
        [e for e in DB.engagements.values() if e["client_project_id"] == project_id]
    )


def decisions_of_batch(batch_id):
    return by_created(
        [d for d in DB.qp_decisions.values() if d["batch_order_id"] == batch_id]
    )
