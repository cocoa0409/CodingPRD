"""In-memory data store.

Every collection starts EMPTY on every boot; nothing is seeded, preloaded or
hardcoded.  Every row is created by a client through a declared endpoint.
"""
import uuid

import clock

cycles = {}
eligibility_rules = {}
voter_blocs = {}
candidates = {}
candidacies = {}
electors = {}
ballots = {}
ballot_slots = {}
vote_submissions = {}
inductions = {}
travel_grants = {}
exhibit_cases = {}
exhibit_installations = {}

ALL_TABLES = [
    cycles,
    eligibility_rules,
    voter_blocs,
    candidates,
    candidacies,
    electors,
    ballots,
    ballot_slots,
    vote_submissions,
    inductions,
    travel_grants,
    exhibit_cases,
    exhibit_installations,
]

_counter = {"n": 0}


def new_id():
    return str(uuid.uuid4())


def _next_seq():
    _counter["n"] += 1
    return _counter["n"]


def stamp(row, versioned=True):
    """Attach identity, creation timestamp and (optionally) version fields."""
    instant = clock.now()
    row["id"] = new_id()
    row["created_at"] = instant
    row["_seq"] = _next_seq()
    if versioned:
        row["updated_at"] = instant
        row["version"] = 1
    return row


def touch(row):
    """Every mutation of a row refreshes updated_at and bumps version by 1."""
    if row is None:
        return row
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = clock.now()
    return row


def sort_rows(rows):
    """List ordering: created_at ASC, then id ASC (PRD 2.3)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))


def creation_order(rows):
    """Cascade processing order: ascending created_at, oldest row first."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def reset_all():
    for table in ALL_TABLES:
        table.clear()
    _counter["n"] = 0
    clock.reset()
