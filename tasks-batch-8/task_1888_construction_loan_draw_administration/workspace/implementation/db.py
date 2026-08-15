"""In-memory data store. Starts empty on every boot — no seeding of any kind."""

import threading
import uuid
from datetime import datetime, timezone

lock = threading.RLock()

borrowers = {}
loans = {}
budget_lines = {}
draws = {}
draw_line_items = {}
draw_documents = {}
inspections = {}
reallocation_requests = {}
retainage_releases = {}
conversion_reviews = {}
interest_entries = {}

_order_counter = [0]


def next_order():
    _order_counter[0] += 1
    return _order_counter[0]


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def base_record():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_order": next_order(),
    }


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = now_iso()


def pub(rec):
    """Public serialization: strip internal (underscore-prefixed) fields."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
