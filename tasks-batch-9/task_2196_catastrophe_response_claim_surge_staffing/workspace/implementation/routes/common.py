"""Shared request preamble and list helpers for the route modules."""
from flask import request

import auth
import derive
import envelope
import store
import sync
from errors import fail
from store import sorted_rows


def begin():
    """Ladder positions 1-3, then the clock-driven re-evaluation of PRD 2.6."""
    user, role = auth.enforce()
    sync.sync_all()
    return user, role


def listing(rows, serializer, sort_key="created_at"):
    limit, offset = envelope.pagination()
    ordered = sorted_rows(rows, sort_key)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return envelope.listing([serializer(r) for r in page], limit, offset, total)


def filter_arg(rows, param, field):
    value = request.args.get(param)
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


def filter_status(rows, param="status", field="status"):
    return filter_arg(rows, param, field)


def require_open_posture(event):
    """Ladder position 20 - the seven frozen-posture child operations."""
    if derive.event_posture(event) == "FROZEN":
        fail("ERR_EVENT_POSTURE_FROZEN")


def require_no_moratorium(event_id):
    """Ladder position 21."""
    if derive.event_moratorium_active(event_id):
        fail("ERR_MORATORIUM_ACTIVE")


def event_of_claim(claim):
    return store.events.get(claim["event_id"])
