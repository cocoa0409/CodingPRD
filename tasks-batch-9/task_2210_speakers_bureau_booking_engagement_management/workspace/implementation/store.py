"""Row construction, audit-field maintenance and serialization helpers.

Public fields are stored JSON-ready on the row.  Internal bookkeeping lives on
keys prefixed with "_" and is never serialized.
"""

import uuid

from flask import g

import db
from timeutil import fmt_iso, wall_now


def new_row(fields, versioned=True):
    """Create a row with §2.4 audit fields.

    `versioned=False` is used for Feedback, which is append-only and carries
    only `id` and `created_at`.
    """
    now = wall_now()
    row = {"id": str(uuid.uuid4()), "created_at": fmt_iso(now)}
    row.update(fields)
    if versioned:
        row["updated_at"] = fmt_iso(now)
        row["version"] = 1
    row["_seq"] = db.next_seq()
    row["_created_ts"] = now
    return row


def touch(row):
    """Refresh updated_at and bump version, once per row per request."""
    if row is None or "version" not in row:
        return row
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    key = row["id"]
    if key in touched:
        return row
    touched.add(key)
    row["updated_at"] = fmt_iso(wall_now())
    row["version"] = row["version"] + 1
    return row


def public(row):
    """Strip internal keys."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sort_created_asc(rows):
    return sorted(rows, key=lambda r: (r["_created_ts"], r["_seq"]))
