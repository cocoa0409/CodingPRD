"""Shared route helpers: lookup-or-404, sorted listing."""
import errors
from errors import err
from response import list_response, success
from validation import pagination_params, paginate


def lookup(table, resource_id):
    """Return the entity or raise ERR_NOT_FOUND."""
    entity = table.get(resource_id)
    if entity is None:
        raise err(errors.ERR_NOT_FOUND, "Resource not found.")
    return entity


def sorted_by_created(items):
    """Default sort: created_at ascending, with a monotonic seq tiebreak (PRD §2.3)."""
    return sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))


def list_and_respond(items, serializer):
    """Sort by created_at asc, paginate, serialize, and wrap in list envelope."""
    limit, offset = pagination_params()
    ordered = sorted_by_created(items)
    window, total = paginate(ordered, limit, offset)
    data = [serializer(e) for e in window]
    return list_response(data, limit, offset, total)


def respond(entity_json, status=200):
    return success(entity_json, status=status, response_type="object")
