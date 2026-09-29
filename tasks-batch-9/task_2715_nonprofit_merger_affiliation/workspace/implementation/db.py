"""In-memory data store.

Storage is Python dictionaries only. The store starts completely empty on every
boot: nothing is seeded, preloaded or hardcoded. Every entity a test needs is
built through the declared API surface.
"""

import random
import string
import uuid

from flask import g

from clock import CLOCK

# Every persisted collection, keyed by id.
ORGANIZATIONS = {}
PROGRAMS = {}
RESTRUCTURINGS = {}
ASSESSMENTS = {}
LETTERS = {}
DILIGENCE = {}
FUNDS = {}
APPROVALS = {}
FILINGS = {}
TASKS = {}

COLLECTIONS = {
    "Organization": ORGANIZATIONS,
    "Program": PROGRAMS,
    "Restructuring": RESTRUCTURINGS,
    "AlignmentAssessment": ASSESSMENTS,
    "LetterOfIntent": LETTERS,
    "DiligenceRequest": DILIGENCE,
    "RestrictedFund": FUNDS,
    "BoardApproval": APPROVALS,
    "AGFiling": FILINGS,
    "IntegrationTask": TASKS,
}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def create_row(kind, fields, versioned=True):
    """Insert a new row. Version starts at 1 and the row counts as already
    touched for this request, so a same-request side effect never bumps it to 2.
    """
    now = CLOCK.now_iso()
    row = {"id": new_id(), "created_at": now}
    if versioned:
        row["updated_at"] = now
        row["version"] = 1
    row.update(fields)
    row["_kind"] = kind
    row["_seq"] = next_seq()
    COLLECTIONS[kind][row["id"]] = row
    if versioned:
        _mark(kind, row["id"])
    return row


def _touched_set():
    marked = getattr(g, "_touched_rows", None)
    if marked is None:
        marked = set()
        g._touched_rows = marked
    return marked


def _mark(kind, row_id):
    _touched_set().add((kind, row_id))


def touch(row):
    """Refresh updated_at and increase version by exactly one — but at most once
    per request per row (PRD 2.5: version arithmetic is per request, not per
    side effect).
    """
    if row is None or "version" not in row:
        return row
    key = (row["_kind"], row["id"])
    marked = _touched_set()
    if key in marked:
        return row
    marked.add(key)
    row["version"] += 1
    row["updated_at"] = CLOCK.now_iso()
    return row


def all_rows(kind):
    return list(COLLECTIONS[kind].values())


def by_created(rows):
    """Default list ordering: created_at ascending, insertion order as the
    deterministic tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def reset_all():
    for coll in COLLECTIONS.values():
        coll.clear()
    _SEQ["n"] = 0
    CLOCK.reset()
