"""Small route-level helpers: path/FK resolution (rungs 10-11) and list plumbing."""

from flask import request

import derive
import envelope
from errors import not_found
from store import DB, ordered
from validation import check_pagination


def must(entity, row_id):
    """Rung 10/11: resolve a row or report the PRD 2.11 not-found code for its
    entity -- fixed by the entity alone, not by the endpoint or the caller."""
    row = DB.get(entity, row_id)
    if row is None:
        raise not_found(entity)
    return row


def must_fk(entity, row_id):
    """A nullable body foreign key: absent is fine, present must resolve."""
    if row_id is None:
        return None
    return must(entity, row_id)


def listing(entity, rows, filters=None):
    """PRD 2.3: filters combine conjunctively, ordering is created_at ascending,
    and a filter naming a value no row carries yields an empty array with a
    total_count of zero rather than an error."""
    limit, offset = check_pagination(request.args)
    selected = list(rows)
    for field, value in (filters or {}).items():
        if value is None:
            continue
        selected = [r for r in selected if _matches(r, field, value)]
    selected = ordered(selected)
    total = len(selected)
    page = selected[offset:offset + limit]
    serializer = derive.SERIALIZERS[entity]
    return envelope.listing([serializer(r) for r in page], limit, offset, total)


def _matches(row, field, value):
    current = row.get(field)
    if isinstance(current, bool):
        return str(current).lower() == str(value).lower()
    if current is None:
        return False
    return str(current) == str(value)


def query_filters(names):
    out = {}
    for name in names:
        raw = request.args.get(name)
        if raw is not None and raw != "":
            out[name] = raw
    return out


def latch_all(entity):
    """Re-derive every clock-dependent posture on a list read (PRD 2.4)."""
    rows = DB.all(entity)
    if entity == "IntakeRecord":
        for r in rows:
            derive.latch_hold(r)
    elif entity == "FosterApplication":
        for r in rows:
            derive.lapse_home_check(r)
    elif entity == "HealthCertificate":
        for r in rows:
            derive.expire_certificate(r)
    return rows
