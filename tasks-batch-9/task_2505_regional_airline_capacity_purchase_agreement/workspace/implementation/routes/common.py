"""Shared helpers for the route modules."""

from flask import request

from db import ordered, public, store
from errors import fail
from response import listing

API_PREFIX = "/cpa"


def filter_rows(rows, spec):
    """Apply the declared query filters.

    spec is a sequence of (query_parameter, entity_field, allowed_values_or_None);
    an unrecognised enum member is a structurally invalid query (PRD 2.12 item 5).
    """
    args = request.args
    for param, field, allowed in spec:
        raw = args.get(param)
        if raw is None:
            continue
        if allowed is not None and raw not in allowed:
            fail("ERR_INVALID_REQUEST",
                 "%s must be one of %s" % (param, ", ".join(allowed)))
        rows = [row for row in rows if row.get(field) == raw]
    return rows


def collection_listing(collection_name, spec):
    rows = ordered(getattr(store, collection_name).values())
    rows = filter_rows(rows, spec)
    return listing(rows, public, request.args)


def guard_terminal(entity, terminal_states, field="status"):
    """PRD 3.1: the already-terminal guard, scoped to the action endpoints that
    declare it.  Evaluated before the transition-declared check so that the code
    is reachable."""
    if entity[field] in terminal_states:
        fail("ERR_ALREADY_TERMINAL")


def guard_state(condition, message=None):
    if not condition:
        fail("ERR_INVALID_STATE", message)


def cycle_of(entity):
    return store.schedule_cycles[entity["cycle_id"]]


def agreement_of(entity):
    return store.agreements[entity["agreement_id"]]
