import itertools
import uuid
from datetime import datetime, timezone

STORE_NAMES = [
    "allergens", "lines", "matrix", "products", "runs", "procedures",
    "changeovers", "swabs", "technicians", "recons", "reworks",
    "incidents", "findings",
]

db = {name: {} for name in STORE_NAMES}
db["_seq"] = itertools.count(1)

# Logical clock: starts exactly at 2026-05-01T00:00:00Z and never uses wall time.
CLOCK = {"current": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(db["_seq"])


def now_iso():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def new_entity(fields):
    ts = now_iso()
    ent = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    ent.update(fields)
    return ent


def touch(ent):
    ent["version"] += 1
    ent["updated_at"] = now_iso()


def public(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}
