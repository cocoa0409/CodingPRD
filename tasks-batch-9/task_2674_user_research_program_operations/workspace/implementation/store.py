"""In-memory data store (PRD section 2.4).

The store starts completely empty on every boot: nothing is seeded, preloaded
or hardcoded. Tests build all state through the API.
"""
import uuid

from clock import clock

TABLES = (
    "decisions", "requests", "pools", "participants", "studies", "recruitments",
    "consents", "artifacts", "themes", "findings", "links", "readouts", "followups",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in TABLES:
            setattr(self, name, {})
        self._seq = 0
        self._dirty = {}
        self._fresh = set()

    # ---- request lifecycle -------------------------------------------------
    def begin_request(self):
        self._dirty = {}
        self._fresh = set()

    def mark(self, entity):
        """Register a row as mutated by the current request.

        Section 2.4: version advances by exactly 1 per mutation of a row, and a
        cascade that touches a row several times inside one request still only
        advances that row once (a settlement walk moves the ledger many times
        but "increments the pool's version by 1").
        """
        if entity is None:
            return
        if entity["id"] in self._fresh:
            return
        self._dirty[entity["id"]] = entity

    def commit(self):
        if not self._dirty:
            return
        stamp = clock.now()
        for entity in self._dirty.values():
            entity["version"] = entity["version"] + 1
            entity["updated_at"] = stamp
        self._dirty = {}

    # ---- creation ----------------------------------------------------------
    def new(self, table, fields):
        stamp = clock.now()
        self._seq += 1
        entity = {
            "id": str(uuid.uuid4()),
            "created_at": stamp,
            "updated_at": stamp,
            "version": 1,
            "_seq": self._seq,
        }
        entity.update(fields)
        getattr(self, table)[entity["id"]] = entity
        self._fresh.add(entity["id"])
        return entity

    def delete(self, table, entity):
        getattr(self, table).pop(entity["id"], None)
        self._dirty.pop(entity["id"], None)


db = Store()


def by_created(rows):
    """Sort by created_at ascending; insertion sequence breaks ties because the
    logical clock can stamp many rows with the same instant."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
