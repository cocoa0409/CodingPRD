"""Entity lifecycle helpers: id/timestamp minting, versioning, serialization."""
from datetime import datetime
from uuid import uuid4

from store import store
from helpers import render_dt


def new_id():
    return str(uuid4())


def base_common(versioned=True):
    """Common system fields at creation time."""
    now = store.now()
    rec = {
        "id": new_id(),
        "created_at": now,
        "_seq": store.next_seq(),
    }
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump version + updated_at on any mutation that changes the resource."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = store.now()


def serialize(rec):
    """Strip internal keys and render every datetime with the single renderer."""
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = render_dt(v)
        else:
            out[k] = v
    return out
