"""Shared route helpers: body parsing, list filtering, pagination wiring."""
from flask import request

import errors
from response import array_response, object_response
from middleware import parse_pagination
from services.common import serialize, sort_by_created, paginate


def get_json_body():
    """Return the parsed JSON body, or {} when there is none.

    Malformed JSON -> ERR_INVALID_REQUEST (400)."""
    if request.data:
        try:
            body = request.get_json(force=True, silent=False)
        except Exception:
            raise errors.invalid_request("Request body is not valid JSON.")
        if body is None:
            return {}
        if not isinstance(body, dict):
            raise errors.invalid_request("Request body must be a JSON object.")
        return body
    return {}


def list_response(records, view_fn=None):
    """Sort by created_at ASC, paginate, and serialize a list of records."""
    limit, offset = parse_pagination()
    ordered = sort_by_created(list(records))
    page, total = paginate(ordered, limit, offset)
    items = [serialize(view_fn(r) if view_fn else r) for r in page]
    return array_response(items, limit, offset, total)


def single_response(record, status=200, view_fn=None):
    rec = view_fn(record) if view_fn else record
    return object_response(serialize(rec), status)
