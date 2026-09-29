"""Shared route helpers."""
from flask import g

import core
from db import store
from errors import fail
from response import list_response
from shapes import pagination


def find(kind, row_id, error_id):
    row = store.collection(kind).get(row_id) if row_id is not None else None
    if row is None:
        fail(error_id)
    return row


def acting_qi():
    """The QualifiedIndividual row named by X-User-ID, or None."""
    return store.qis.get(g.user_id)


def require_qi_current(qi=None):
    """Ladder rung 26 — ERR_QI_DESIGNATION_INVALID."""
    row = qi if qi is not None else acting_qi()
    if not core.qi_is_current(row):
        fail("ERR_QI_DESIGNATION_INVALID")
    return row


def paged(rows, serializer, limit=None, offset=None):
    if limit is None or offset is None:
        limit, offset = pagination()
    ordered = core.sort_rows(rows)
    total = len(ordered)
    window = ordered[offset : offset + limit]
    return list_response([serializer(r) for r in window], limit, offset, total)
