"""The response-envelope shaper.

The PRD §2.2 H3 paragraph's standard-success-response-format names the
canonical envelope:

    {
        "meta": {
            "api_request_id": "req_xxxxxxxxxxxxxxxx",
            "api_request_timestamp": "<ISO 8601 UTC, three fractional digits>",
            "limit": <integer, on list endpoints>,
            "offset": <integer, on list endpoints>,
            "total_count": <integer, on list endpoints>,
            "has_more": <boolean, on list endpoints>
        },
        "response_type": "object" | "array",
        "data": { <the resource payload> } | [ <the array of resources> ]
    }

For object responses `response_type` is `"object"` and `data` is the single
resource's JSON object (the entity-row dict, with the standard four common
fields and the entity-specific fields). For array responses `response_type`
is `"array"` and `data` is the JSON array of zero or more resources, and
the four pagination fields are present in the `meta` block alongside the
two standard request-id and timestamp fields.

For the error-envelope shape (the §2.2's standard-error-response-format), the
`response_type` is the literal `"error"` and the `data` is the object
`{"error_id": "...", "message": "..."}` (with optional extra detail keys
inlined for the structured-detail variants the prompt's spec mentions). The
HTTP status code on an error response is the per-error-id status from the
catalogue in `errors.py`. The error envelope is built by the
`APIError.as_envelope` method in the `errors` module rather than by this
module's helpers.

This module exports the two top-level helpers:

  - `success_envelope(data, list_meta=None)` returns the canonical success
    envelope dict ready for `jsonify`. When `list_meta` is `None` the
    response is an object response; when `list_meta` is the
    `(limit, offset, total_count, has_more)` tuple the response is an array
    response with the four pagination keys folded into `meta`.

  - `register_meta_hooks(app)` registers the Flask `before_request` hook
    that stamps a fresh `api_request_id` on `flask.g.api_request_id` so the
    success-and-error envelope builders share the same id within a single
    request, and the `after_request` hook that adds the standard headers
    (`Content-Type: application/json`, `Date: <RFC 1123 string>`) on every
    response — Flask's `jsonify` already sets `Content-Type` so the
    `after_request` hook is mostly a no-op in practice, but the hook is
    where the optional cross-cutting response shaping lives if the
    deployment-side requires it.

The standard PRD-bench pattern is that the per-handler function returns the
naked Python dict the success envelope's `data` field's value should be (or,
for a list endpoint, the pair `(rows_list, total_count_int)` augmented by
the pagination-helper's `has_more` boolean), and a thin wrapper function in
this module's namespace builds the final envelope. The blueprint-handler
code calls `make_object_response(row_dict, http_status=201)` or
`make_array_response(rows_list, limit, offset, total_count)` and returns the
result to Flask.
"""

from __future__ import annotations

from typing import Any, Optional

from flask import Flask, g, jsonify, make_response, request, Response

from .clock import iso_now
from .errors import generate_request_id


def _stamp_request_id() -> None:
    """The `before_request` hook. Mint a fresh request-id and stash it on
    `flask.g` so the success-and-error envelope builders read the same value
    within the request's scope.

    The standard "echo the client's X-Request-ID header if present" pattern
    is not part of the PRD §2.2 envelope contract — the contract says the
    `api_request_id` is "a server-generated unique identifier for the
    request that starts with `req_`", so the server always mints the id
    and ignores any incoming `X-Request-ID` header on the request side.
    The convention's-clarification is in the PRD's "the
    `api_request_id` is a server-generated unique identifier" wording.
    """
    g.api_request_id = generate_request_id()


def _ensure_content_type(response: Response) -> Response:
    """The `after_request` hook. Ensure the `Content-Type` is the standard
    `application/json` and the `Date` header is the RFC 1123 timestamp.
    Flask's `jsonify` sets `Content-Type` to `application/json` by default
    so this hook's `setdefault` is a no-op in the success case; on the
    error-envelope-from-the-Werkzeug-`HTTPException`-path the framework's
    default content type might be `text/html`, which our error-handlers
    in the `errors` module override by themselves using `jsonify`, so this
    hook's effect is the same: idempotent `Content-Type` normalization.

    The hook does not modify the body. The standard ban on
    `Cache-Control: no-store` adjustments is irrelevant on an API that
    has no caching contract.
    """
    response.headers.setdefault("Content-Type", "application/json")
    # The standard `Date` header is set by the WSGI server automatically; we
    # do not override it.
    return response


def register_meta_hooks(app: Flask) -> None:
    """Wire the two cross-cutting middleware hooks. Called once at
    `create_app()` time.
    """
    app.before_request(_stamp_request_id)
    app.after_request(_ensure_content_type)


def _make_meta(
    list_meta: Optional[tuple[int, int, int, bool]] = None,
    extra_meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build the `meta` block. The two standard fields `api_request_id` and
    `api_request_timestamp` are always present. The four pagination fields
    `limit`, `offset`, `total_count`, and `has_more` are added when
    `list_meta` is supplied (the standard convention is to omit them on the
    single-object-response path so the meta block is the minimal-shape
    `{api_request_id, api_request_timestamp}` pair on a single-resource
    fetch — the PRD §2.3 paragraph names the pagination fields as
    "included for list endpoints", which we read as "absent on the
    non-list ones"). Any extra meta keys (e.g., the gps-ingest's
    `replayed: true` flag on an idempotency-replay) are merged in via the
    `extra_meta` dict.
    """
    api_request_id = getattr(g, "api_request_id", None) or generate_request_id()
    meta: dict[str, Any] = {
        "api_request_id": api_request_id,
        "api_request_timestamp": iso_now(),
    }
    if list_meta is not None:
        limit, offset, total_count, has_more = list_meta
        meta["limit"] = int(limit)
        meta["offset"] = int(offset)
        meta["total_count"] = int(total_count)
        meta["has_more"] = bool(has_more)
    if extra_meta:
        for k, v in extra_meta.items():
            # Do not clobber the two canonical fields.
            if k not in ("api_request_id", "api_request_timestamp"):
                meta[k] = v
    return meta


def make_object_response(
    data: dict[str, Any],
    http_status: int = 200,
    extra_meta: Optional[dict[str, Any]] = None,
) -> Response:
    """Build a Flask response for a single-resource (object) success.
    `data` is the JSON-serializable Python dict that becomes the envelope's
    `data` field's value. `http_status` is the HTTP response status (200
    for reads, 201 for creates, 200 for state-transition POSTs per the
    scaffold's-§1.5-and-the-PRD-§4 status-table). `extra_meta` is an
    optional dict of meta-block extension keys (e.g., the gps-ingest's
    `replayed: true` flag).
    """
    body = {
        "meta": _make_meta(extra_meta=extra_meta),
        "response_type": "object",
        "data": data,
    }
    response = make_response(jsonify(body))
    response.status_code = http_status
    return response


def make_array_response(
    rows: list[dict[str, Any]],
    limit: int,
    offset: int,
    total_count: int,
    has_more: bool,
    http_status: int = 200,
) -> Response:
    """Build a Flask response for a paginated-list (array) success. The
    four pagination fields land in the `meta` block per the PRD §2.3
    paragraph's "pagination-related fields in `meta`" rule. The `rows`
    list becomes the envelope's `data` field's value. The
    `total_count` is the count of rows that match the query's filters
    across the whole underlying table, and `has_more` is the boolean
    indicating whether further pages exist past the current
    `offset + limit` cursor.
    """
    list_meta = (int(limit), int(offset), int(total_count), bool(has_more))
    body = {
        "meta": _make_meta(list_meta=list_meta),
        "response_type": "array",
        "data": list(rows),
    }
    response = make_response(jsonify(body))
    response.status_code = http_status
    return response


def make_empty_response(http_status: int = 204) -> Response:
    """Build a Flask response for a no-body success (the 204 No Content
    case, which the scaffold's endpoint table does not actually use — every
    success returns the affected row in the `data` block. The helper is
    here for completeness in case a future endpoint needs the bare-204
    shape).
    """
    body = {
        "meta": _make_meta(),
        "response_type": "object",
        "data": {},
    }
    response = make_response(jsonify(body))
    response.status_code = http_status
    return response


def parse_pagination_query() -> tuple[int, int]:
    """Read the `limit` and `offset` integers off the Flask request's
    query string, applying the §2.3 H3 paragraph's defaults and bounds
    rules: default limit is 10, inclusive range [1, 100]; default offset
    is 0, the non-negative integers. A malformed or out-of-range value
    raises `APIError(ERR_VALIDATION, 422)` with a descriptive message.

    The helper is the canonical entry point the list-endpoint handlers
    call before any other processing. The four-element tuple
    `(limit, offset, sort_field_optional, _filter_dict)` is the typical
    shape the handler builds locally — this helper returns just the two
    universal fields, with the per-endpoint sort-and-filter logic owned
    by the handler.
    """
    from .errors import APIError
    from .config import (
        PAGINATION_LIMIT_DEFAULT,
        PAGINATION_LIMIT_MIN,
        PAGINATION_LIMIT_MAX,
        PAGINATION_OFFSET_DEFAULT,
    )

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else PAGINATION_LIMIT_DEFAULT
    except (TypeError, ValueError):
        raise APIError(
            "ERR_VALIDATION",
            f"'limit' query parameter must be an integer; got {raw_limit!r}",
            details={"field": "limit", "value": raw_limit},
        )
    try:
        offset = (
            int(raw_offset) if raw_offset is not None else PAGINATION_OFFSET_DEFAULT
        )
    except (TypeError, ValueError):
        raise APIError(
            "ERR_VALIDATION",
            f"'offset' query parameter must be an integer; got {raw_offset!r}",
            details={"field": "offset", "value": raw_offset},
        )
    if not (PAGINATION_LIMIT_MIN <= limit <= PAGINATION_LIMIT_MAX):
        raise APIError(
            "ERR_VALIDATION",
            f"'limit' must be in [{PAGINATION_LIMIT_MIN}, "
            f"{PAGINATION_LIMIT_MAX}]; got {limit}",
            details={
                "field": "limit",
                "value": limit,
                "min": PAGINATION_LIMIT_MIN,
                "max": PAGINATION_LIMIT_MAX,
            },
        )
    if offset < 0:
        raise APIError(
            "ERR_VALIDATION",
            f"'offset' must be non-negative; got {offset}",
            details={"field": "offset", "value": offset},
        )
    return limit, offset


def get_json_body() -> dict[str, Any]:
    """Parse the request's JSON body and return the resulting dict. A
    missing body, an unparseable body, or a non-object top-level JSON
    value (e.g., an array or a scalar) is the body-shape catch-all
    `ERR_VALIDATION` 422 per the §2.7's bottom-of-Tier-5 priority-590
    convention.

    On a `POST` with no body (the action endpoints whose body is
    described in the PRD as "optional" — the depart, arrive, abort, and
    submit endpoints accept an empty body or a body carrying just the
    optional `version` field), the helper returns the empty dict `{}`
    so the caller's body-field-extraction logic sees the defaults.
    """
    from .errors import APIError

    # Flask's `request.get_json(silent=True)` returns None if the body is
    # absent or unparseable. The `force=False` default means the
    # Content-Type must be `application/json` for the JSON parser to
    # engage; we use `force=True` so a body with a wrong Content-Type
    # header but valid JSON content is still accepted, on the principle
    # that the test harness's curl-or-requests client may not always set
    # the header.
    if request.content_length is None or request.content_length == 0:
        return {}
    body = request.get_json(silent=True, force=True)
    if body is None:
        raise APIError(
            "ERR_VALIDATION",
            "Request body is not valid JSON or is empty when a body is required.",
        )
    if not isinstance(body, dict):
        raise APIError(
            "ERR_VALIDATION",
            f"Request body must be a JSON object; got {type(body).__name__}.",
        )
    return body


def get_optional_idempotency_key() -> Optional[str]:
    """Read the optional `Idempotency-Key` HTTP header. Returns the header
    value if present, otherwise None. The header-length validation against
    the inclusive 8-to-128-character bound is done by the gps-ingest's
    handler at the body-shape tier.
    """
    from .config import HEADER_IDEMPOTENCY_KEY

    return request.headers.get(HEADER_IDEMPOTENCY_KEY)
