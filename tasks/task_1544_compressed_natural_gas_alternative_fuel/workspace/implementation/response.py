"""Standard response envelope helpers.

Envelope (from SCAFFOLD response_envelope + PRD §2.2):

success:
  { "meta": { "api_request_id": ..., "api_request_timestamp": ...,
              ["limit","offset","total_count","has_more"] for lists },
    "response_type": "object" | "array",
    "data": {...} | [...] }

error:
  { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
    "response_type": "error",
    "data": { "error_id": ..., "message": ... } }
"""
from __future__ import annotations

import json

from flask import Response

from db import isoformat, new_request_id, now_utc


def _meta(include_pagination: bool = False,
          limit: int | None = None,
          offset: int | None = None,
          total_count: int | None = None,
          has_more: bool | None = None) -> dict:
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": isoformat(now_utc()),
    }
    if include_pagination:
        m["limit"] = limit
        m["offset"] = offset
        m["total_count"] = total_count
        m["has_more"] = has_more
    return m


def _json_response(payload: dict, status: int) -> Response:
    body = json.dumps(payload, separators=(",", ":"))
    return Response(body, status=status, mimetype="application/json")


def success_object(data: dict, status: int = 200) -> Response:
    payload = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return _json_response(payload, status)


def success_list(items: list, limit: int, offset: int, total_count: int) -> Response:
    has_more = (offset + len(items)) < total_count
    payload = {
        "meta": _meta(include_pagination=True,
                      limit=limit, offset=offset,
                      total_count=total_count, has_more=has_more),
        "response_type": "array",
        "data": items,
    }
    return _json_response(payload, 200)


def error_response(error_id: str, message: str, http_status: int) -> Response:
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return _json_response(payload, http_status)
