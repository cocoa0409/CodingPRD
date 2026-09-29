"""Shared helpers for route modules."""

from response import array_response, object_response, paginate
from serialize import public, public_list
from valid import pagination


def send(record, status=200):
    return object_response(public(record), status)


def send_data(data, status=200):
    return object_response(data, status)


def send_list(records):
    """Paginate an already-filtered, already-ordered list of records."""
    limit, offset = pagination()
    page, total = paginate(list(records), limit, offset)
    return array_response(public_list(page), limit, offset, total)


def body_ref(body, key, resolver):
    """Resolve a body reference (band 5). Absent/null -> None."""
    if key not in body or body[key] is None:
        return None
    return resolver(body[key])
