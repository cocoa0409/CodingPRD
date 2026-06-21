"""Route-level helpers: body parsing and list pagination/serialization."""

from flask import request

import errors
from errors import err
from middleware import parse_pagination
from response import array_response
from services.serialize import public


def get_json_body():
    """Return the parsed JSON body as a dict (or {} when empty)."""
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        # Empty/None bodies are allowed for action endpoints; only malformed
        # non-empty JSON is rejected.
        if request.data and request.data.strip():
            raise err(errors.ERR_INVALID_REQUEST, "Malformed JSON body")
        return {}
    if not isinstance(body, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def paginated(items):
    """Sort-by-created_at-already-ordered list -> paginated array response."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return array_response([public(i) for i in page], limit, offset, total)


def sort_by_created(items):
    """Stable sort by created_at ASC (PRD §2.3 default order)."""
    return sorted(items, key=lambda e: (e["created_at"], e.get("_seq_create", 0)))
