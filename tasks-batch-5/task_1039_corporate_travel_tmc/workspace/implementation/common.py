"""Small helpers shared across route modules."""

from flask import request

import store
import envelope
import logic
from errors import not_found


def get_or_404(collection, resource_id):
    record = collection.get(resource_id)
    if record is None:
        raise not_found(f"Resource not found: {resource_id}")
    return record


def exists_or_404(collection, value):
    """Existence check for a foreign key (priority 3). Only fires when the value
    is a non-empty string that fails to resolve; a missing/None/non-string value
    is left for the priority-4 body-validation stage."""
    if isinstance(value, str) and value != "" and value not in collection:
        raise not_found(f"Referenced resource not found: {value}")


def single(record, status=200):
    return envelope.success(store.public(record), "object", status)


def list_result(records):
    ordered = logic.sorted_by_creation(list(records))
    page, pagination = envelope.paginate(ordered, request.args)
    data = [store.public(r) for r in page]
    return envelope.success(data, "array", 200, pagination)


def filter_by(records, args, fields):
    """Filter an iterable of records by exact match on the given query params."""
    result = list(records)
    for field, caster in fields.items():
        raw = args.get(field)
        if raw is None:
            continue
        value = caster(raw)
        result = [r for r in result if r.get(field) == value]
    return result


def as_bool(raw):
    return str(raw).lower() in ("true", "1", "yes")


def as_str(raw):
    return raw
