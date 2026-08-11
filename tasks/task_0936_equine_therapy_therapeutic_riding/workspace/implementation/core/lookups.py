"""Rungs 9-13: path and body identifier resolution, left to right."""

from .errors import fail
from .store import db, get


def rider_or_404(rider_id):
    row = get("riders", rider_id)
    if row is None:
        fail("ERR_RIDER_NOT_FOUND", "No rider %r." % rider_id)
    return row


def session_or_404(session_id):
    row = get("sessions", session_id)
    if row is None:
        fail("ERR_SESSION_NOT_FOUND", "No session %r." % session_id)
    return row


def horse_or_404(horse_id):
    row = get("horses", horse_id)
    if row is None:
        fail("ERR_HORSE_NOT_FOUND", "No horse %r." % horse_id)
    return row


def resource_or_404(table, row_id):
    row = get(table, row_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "No %s %r." % (table[:-1], row_id))
    return row


def rows_where(table, **filters):
    out = []
    for row in db[table].values():
        if all(row.get(key) == value for key, value in filters.items()):
            out.append(row)
    return out
