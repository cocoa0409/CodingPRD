"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone

from clock import Clock

# Entities that carry only id + created_at (no updated_at / version) — PRD §2.4.
NO_VERSION_ENTITIES = {"Crew", "CrewShift"}


def real_utc_now_iso():
    """Wall-clock ISO 8601 UTC with millisecond precision (for created_at / meta)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        # kind -> { id -> record dict }
        self.collections = {}
        self.clock = Clock()
        self._seq = 0

    def reset(self):
        self.collections = {}
        self.clock = Clock()
        self._seq = 0

    def _seq_next(self):
        self._seq += 1
        return self._seq

    def coll(self, kind):
        return self.collections.setdefault(kind, {})

    def create(self, kind, fields):
        rid = new_id()
        now = real_utc_now_iso()
        rec = dict(fields)
        rec["id"] = rid
        rec["created_at"] = now
        rec["_kind"] = kind
        rec["_seq"] = self._seq_next()  # monotonic creation order for stable sort
        if kind not in NO_VERSION_ENTITIES:
            rec["updated_at"] = now
            rec["version"] = 1
        self.coll(kind)[rid] = rec
        return rec

    def touch(self, rec):
        """Standard mutation bookkeeping: bump version + updated_at when applicable."""
        if rec.get("_kind") not in NO_VERSION_ENTITIES:
            rec["updated_at"] = real_utc_now_iso()
            rec["version"] = rec.get("version", 1) + 1
        return rec

    def get(self, kind, rid):
        return self.coll(kind).get(rid)

    def all(self, kind):
        return list(self.coll(kind).values())

    def query(self, kind, **filters):
        out = []
        for rec in self.coll(kind).values():
            ok = True
            for k, v in filters.items():
                if v is None:
                    continue
                if rec.get(k) != v:
                    ok = False
                    break
            if ok:
                out.append(rec)
        out.sort(key=lambda r: r["_seq"])
        return out


db = Store()
