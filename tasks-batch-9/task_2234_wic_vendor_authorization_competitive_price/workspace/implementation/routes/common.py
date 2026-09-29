"""Shared route helpers: path/body identifier resolution and list responses."""

from flask import request

import envelope
import validators
from errors import ApiError


def need(collection, entity_id, error_id):
    """Ladder rule 5: resolve a path identifier or raise the matching 404."""
    record = collection.get(entity_id)
    if record is None:
        raise ApiError(error_id)
    return record


def body_fk(payload, field, collection, error_id):
    """Ladder rule 6: resolve a body foreign key when it is present and a string."""
    value = payload.get(field)
    if value is None or not isinstance(value, str):
        return None
    record = collection.get(value)
    if record is None:
        raise ApiError(error_id)
    return record


def listing(items, filters=None):
    """Ladder rule 7 for limit/offset, then equality filters, then the page."""
    limit, offset = validators.pagination()
    if filters:
        for param, field in filters.items():
            raw = request.args.get(param)
            if raw is not None:
                items = [item for item in items if item.get(field) == raw]
    total = len(items)
    return envelope.collection(validators.paginate(items, limit, offset), limit, offset, total)
