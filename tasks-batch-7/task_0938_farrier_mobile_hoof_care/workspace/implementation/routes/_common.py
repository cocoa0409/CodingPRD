"""Shared plumbing for the HTTP layer."""

from core.auth import authenticate
from core.envelope import apply_filters, ok, ok_list, paginate, read_pagination
from core.store import db
from domain.serializers import serialize, serialize_many

ALL_ROLES = (
    "PlatformAdmin",
    "Dispatcher",
    "Farrier",
    "ClientUser",
    "Veterinarian",
    "BillingClerk",
)


def listing(table, filters, roles, rows=None, ordered=None):
    """Standard list endpoint: auth, pagination range check, filters, page."""
    authenticate(roles)
    limit, offset = read_pagination()
    source = ordered if ordered is not None else (rows if rows is not None else db.all(table))
    source = apply_filters(source, filters)
    page, total = paginate(source, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset)


def single(row, status=200):
    return ok(serialize(row), status)
