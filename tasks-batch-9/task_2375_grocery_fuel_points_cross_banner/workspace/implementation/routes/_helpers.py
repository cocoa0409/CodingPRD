"""Shared route plumbing: list pagination and small guard helpers."""
import response
import shape
from errors import ApiError


def listing(items, serializer, order=None):
    limit, offset = shape.pagination()
    rows = sorted(items, key=order) if order is not None else list(items)
    page, total = shape.paginate(rows, limit, offset)
    return response.array_response([serializer(row) for row in page],
                                   limit, offset, total)


def invalid_state(message="the requested transition is not permitted from the current state"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", message)


def require_status(entity, field, allowed, message=None):
    if entity[field] not in allowed:
        raise invalid_state(message or
                            "current %s '%s' does not permit this transition"
                            % (field, entity[field]))
