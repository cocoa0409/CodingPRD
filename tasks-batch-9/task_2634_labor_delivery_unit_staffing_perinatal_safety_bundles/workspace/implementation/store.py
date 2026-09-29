"""In-memory store. Empty at boot: nothing is ever seeded or preloaded."""

import uuid

import clock


class Store(object):
    KINDS = (
        "units", "staff", "shifts", "beds", "encounters", "care", "bookings",
        "activations", "items", "assessments", "cesareans", "drills",
        "reviews", "passes", "snapshots",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        for kind in self.KINDS:
            setattr(self, kind, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


S = Store()


def new_record(fields):
    instant = clock.now()
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": instant,
        "updated_at": instant,
        "version": 1,
        "_seq": S.next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    """Refresh updated_at and increment the revision counter."""
    if rec is None:
        return None
    rec["updated_at"] = clock.now()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def _sort_key(value):
    """Nulls always sort last in the natural (ascending) direction."""
    if value is None:
        return (1, 0)
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float)):
        return (0, value)
    if hasattr(value, "timestamp"):
        return (0, value.timestamp())
    return (0, str(value))


def sort_rows(rows, keys):
    """Stable multi-key sort. `_seq` (insertion order) is the final tie-break,
    taken in the direction of the last declared key; `id` is never a key."""
    last_desc = bool(keys) and keys[-1][1] == "desc"
    result = sorted(rows, key=lambda r: r["_seq"], reverse=last_desc)
    for field, direction in reversed(keys):
        result.sort(key=lambda r, f=field: _sort_key(r.get(f)),
                    reverse=(direction == "desc"))
    return result


def paginate(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    has_more = (offset + len(window)) < total
    return window, total, has_more
