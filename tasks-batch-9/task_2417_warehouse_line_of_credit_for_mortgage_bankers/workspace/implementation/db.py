"""In-memory data store.

Nothing is seeded: every collection starts empty on every boot and every row a
caller needs is created through the declared API surface.
"""

import itertools
import random
import string
import uuid

from clock import fmt_dt, wall_now

_REQUEST_ID_ALPHABET = string.ascii_uppercase + string.digits


class Store(object):
    def __init__(self):
        self.facilities = {}
        self.product_rates = {}
        self.custodians = {}
        self.investors = {}
        self.commitments = {}
        self.advances = {}
        self.wires = {}
        self.receipts = {}
        self.bailee_letters = {}
        self.margin_calls = {}
        self.cure_payments = {}
        self.covenant_tests = {}
        self.demands = {}
        self.ledger_entries = {}
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_REQUEST_ID_ALPHABET) for _ in range(20))


def base_row(with_version=True):
    """Common fields (PRD 2.4).  ``with_version`` is False for the two
    append-only records (CurePayment, LedgerEntry) which carry only ``id`` and
    ``created_at``."""
    stamp = fmt_dt(wall_now())
    row = {"id": new_id(), "created_at": stamp, "_seq": db.next_seq()}
    if with_version:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Every mutated row has its version incremented by 1 and its updated_at
    refreshed (PRD 2.4 / 2.10)."""
    row["updated_at"] = fmt_dt(wall_now())
    row["version"] = row.get("version", 1) + 1
    return row


def by_created_at(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
