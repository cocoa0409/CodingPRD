"""Response envelope helpers and per-request bookkeeping."""
from __future__ import annotations

import secrets
import string
from typing import Any, Optional

from flask import Flask, g, request

from .clock import current_iso_timestamp


_ALPHANUM = string.ascii_uppercase + string.ascii_lowercase + string.digits


def _generate_request_id() -> str:
    # The PRD example uses "req_RANDOMALPHANUM123456" — 20 alphanumeric chars
    suffix = "".join(secrets.choice(_ALPHANUM) for _ in range(20))
    return f"req_{suffix}"


def _make_meta(pagination: Optional[dict] = None) -> dict:
    meta = {
        "api_request_id": getattr(g, "api_request_id", _generate_request_id()),
        "api_request_timestamp": getattr(g, "api_request_timestamp", current_iso_timestamp()),
    }
    if pagination:
        meta.update(pagination)
    return meta


def build_envelope(data: Any, response_type: str = "object", pagination: Optional[dict] = None) -> dict:
    return {
        "meta": _make_meta(pagination),
        "response_type": response_type,
        "data": data,
    }


def error_envelope(error_id: str, message: str) -> dict:
    return {
        "meta": _make_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }


def register_request_hooks(app: Flask) -> None:
    @app.before_request
    def _attach_request_meta():
        g.api_request_id = _generate_request_id()
        g.api_request_timestamp = current_iso_timestamp()
