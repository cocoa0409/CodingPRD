"""In-memory store. Starts completely empty on every boot -- nothing is seeded."""
import itertools
import threading
import uuid

import clock

school_partners = {}
calendar_blackouts = {}
teaching_artists = {}
portfolio_reviews = {}
background_screenings = {}
arts_standards = {}
residencies = {}
lesson_plans = {}
sessions = {}
evaluation_records = {}
payment_vouchers = {}
funder_reports = {}

lock = threading.RLock()

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def base_row(versioned=True):
    stamp = clock.real_now_iso()
    row = {"id": new_id(), "created_at": stamp, "_seq": next_seq()}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and bump version (PRD 2.7).

    Idempotent within a single request: a row mutated several times by one
    request (cascades often revisit the same residency) is stamped once, because
    PRD 2.7 specifies one increment per mutated row per request.
    """
    if row is None or "version" not in row:
        return
    try:
        from flask import g, has_request_context
        if has_request_context():
            seen = getattr(g, "_touched_rows", None)
            if seen is None:
                seen = set()
                g._touched_rows = seen
            key = id(row)
            if key in seen:
                return
            seen.add(key)
    except Exception:
        pass
    row["updated_at"] = clock.real_now_iso()
    row["version"] = row["version"] + 1


def ordered(collection):
    """Default list order: created_at ascending (insertion sequence)."""
    return sorted(collection, key=lambda r: r["_seq"])
