"""Shared list/filter plumbing for the route modules."""
import db
import response
import validate


def apply_filters(rows, fields):
    """Keep rows matching every supplied query filter (filters combine conjunctively)."""
    for field in fields:
        wanted = validate.filter_value(field)
        if wanted is None:
            continue
        rows = [row for row in rows if str(row.get(field)) == wanted]
    return rows


def apply_membership_filter(rows, field, param=None):
    """Filter rows whose list-valued `field` contains the supplied identifier."""
    wanted = validate.filter_value(param or field)
    if wanted is None:
        return rows
    return [row for row in rows if wanted in (row.get(field) or [])]


def apply_bool_filter(rows, field):
    wanted = validate.filter_bool(field)
    if wanted is None:
        return rows
    return [row for row in rows if bool(row.get(field)) is wanted]


def list_response(rows, ordered=False):
    """Paginate and envelope a list, ordered by created_at ascending by default."""
    limit, offset = validate.pagination()
    if not ordered:
        rows = db.by_created(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return response.listing([response.public(row) for row in page], limit, offset, total)
