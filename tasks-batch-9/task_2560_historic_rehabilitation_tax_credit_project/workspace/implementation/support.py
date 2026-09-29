"""Small shared helpers for the route modules."""

import re

from db import public
from errors import ApiError
from response import list_response
from validate import bad

_CODE_RE = re.compile(r"^[A-Z]{2}$")


def fetch(table, key, error_id):
    """Band 4/5: resolve an id or raise the entity's own not-found error."""
    record = table.get(key)
    if record is None:
        raise ApiError(error_id)
    return record


def state_code(data, name):
    value = data.get(name)
    if not isinstance(value, str) or not _CODE_RE.match(value):
        raise bad("Field '%s' must be two uppercase letters." % name)
    return value


def respond_list(rows, limit, offset, transform=None):
    total = len(rows)
    page = rows[offset: offset + limit]
    render = transform or public
    return list_response([render(row) for row in page], limit, offset, total)


def filter_eq(rows, field, value):
    if value is None:
        return rows
    return [row for row in rows if row.get(field) == value]
