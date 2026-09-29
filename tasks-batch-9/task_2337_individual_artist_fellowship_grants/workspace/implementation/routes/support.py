"""Shared route helpers: path resolution, listing, redaction."""

import db
import constants as C
import middleware
import response
import validation
from errors import ApiError

ALL_ROLES = middleware.ROLES
NO_PANELIST = tuple(r for r in middleware.ROLES if r != middleware.PANELIST)


def resolve(table, row_id):
    """P40: a path id that resolves to nothing yields the entity-specific 404."""
    row = db.get(table, row_id)
    if row is None:
        raise ApiError(C.NOT_FOUND[table])
    return row


def resolve_fk(table, row_id):
    """P45: a body foreign key that resolves to nothing yields the same 404."""
    row = db.get(table, row_id)
    if row is None:
        raise ApiError(C.NOT_FOUND[table])
    return row


def eq(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


def listed(items, view=db.public):
    limit, offset = validation.pagination()
    total = len(items)
    window = items[offset : offset + limit]
    return response.collection([view(r) for r in window], limit, offset, total)


def application_view(role):
    """Panelists never resolve an applicant identity before unsealing."""

    def view(row):
        data = db.public(row)
        if role == middleware.PANELIST and row["anonymity_status"] != "UNSEALED":
            data["applicant_legal_name"] = None
            data["applicant_region"] = None
        return data

    return view


def clock_iso():
    return db.iso3(db.now())


def require_state(condition, error_id):
    if not condition:
        raise ApiError(error_id)
