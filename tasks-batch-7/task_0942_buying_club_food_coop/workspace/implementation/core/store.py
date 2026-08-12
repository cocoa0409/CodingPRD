"""In-memory store.  Python dicts keyed by id.  Nothing is seeded at startup.

Ids are server-minted UUID strings with no type prefix.  They are monotonic and
predictable per entity type: the low 64 bits are a per-type counter and the high
bits carry the type index, so ids never collide across types and always sort in
creation order within a type.

Every row also carries a private `_seq` insertion ordinal.  Because the logical
clock does not advance on its own, many rows share a `created_at` value to the
millisecond; `_seq` is the pinned write-order tie-break behind `created_at ASC`.
"""

import uuid

from . import clock

_TYPE_INDEX = {
    "Member": 1,
    "Route": 2,
    "DropPoint": 3,
    "Item": 4,
    "PriceVersion": 5,
    "Cycle": 6,
    "RouteRun": 7,
    "DropRun": 8,
    "MemberOrder": 9,
    "OrderLine": 10,
    "CaseAggregate": 11,
    "ReceiptLine": 12,
    "SubstitutionOffer": 13,
    "Pallet": 14,
    "Payment": 15,
    "DropReconciliation": 16,
    "CommissionAccrual": 17,
    "VolunteerShift": 18,
    "CreditGrant": 19,
}

_COLLECTION = {
    "Member": "members",
    "Route": "routes",
    "DropPoint": "drop_points",
    "Item": "items",
    "PriceVersion": "price_versions",
    "Cycle": "cycles",
    "RouteRun": "route_runs",
    "DropRun": "drop_runs",
    "MemberOrder": "member_orders",
    "OrderLine": "order_lines",
    "CaseAggregate": "case_aggregates",
    "ReceiptLine": "receipt_lines",
    "SubstitutionOffer": "substitution_offers",
    "Pallet": "pallets",
    "Payment": "payments",
    "DropReconciliation": "drop_reconciliations",
    "CommissionAccrual": "commission_accruals",
    "VolunteerShift": "volunteer_shifts",
    "CreditGrant": "credit_grants",
}


class Store:
    def __init__(self):
        for name in _COLLECTION.values():
            setattr(self, name, {})
        self._counters = {kind: 0 for kind in _TYPE_INDEX}
        self._seq = 0
        self._request_counter = 0

    # -- id minting -----------------------------------------------------------
    def next_id(self, kind):
        self._counters[kind] += 1
        value = (_TYPE_INDEX[kind] << 64) | self._counters[kind]
        return str(uuid.UUID(int=value))

    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_request_id(self):
        self._request_counter += 1
        alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        n = self._request_counter
        digits = ""
        while n:
            digits = alphabet[n % 36] + digits
            n //= 36
        return "req_" + digits.rjust(20, "0")

    # -- row lifecycle --------------------------------------------------------
    def collection(self, kind):
        return getattr(self, _COLLECTION[kind])

    def insert(self, kind, fields, versioned=True):
        row = dict(fields)
        row["_kind"] = kind
        row["id"] = self.next_id(kind)
        row["_seq"] = self.next_seq()
        row["created_at"] = clock.now_iso()
        if versioned:
            row["updated_at"] = row["created_at"]
            row["version"] = 1
        self.collection(kind)[row["id"]] = row
        return row

    def get(self, kind, row_id):
        if not isinstance(row_id, str):
            return None
        return self.collection(kind).get(row_id)

    def all(self, kind):
        """Every row of a kind in the pinned default order: created_at ASC,
        then write order within one clock reading."""
        return sorted(self.collection(kind).values(),
                      key=lambda r: (r["created_at"], r["_seq"]))


DB = Store()


def reset():
    global DB
    DB = Store()


def touch(row):
    """Record a mutation of a row: bump version and refresh updated_at."""
    if "version" in row:
        row["version"] += 1
        row["updated_at"] = clock.now_iso()
    return row


def touch_if_changed(row, before):
    """Bump only when at least one stored value actually changed."""
    changed = any(row.get(k) != v for k, v in before.items())
    if changed:
        touch(row)
    return changed


def snapshot(row, keys):
    return {k: row.get(k) for k in keys}


def ordered(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
