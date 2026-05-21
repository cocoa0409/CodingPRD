"""Response envelope helpers per §2.2."""
from __future__ import annotations

import secrets
import string
from typing import Any

from flask import jsonify

from .clock import now_iso


_ALPHABET = string.ascii_uppercase + string.digits


def _make_request_id() -> str:
    return "req_" + "".join(secrets.choice(_ALPHABET) for _ in range(20))


def _base_meta() -> dict:
    return {
        "api_request_id": _make_request_id(),
        "api_request_timestamp": now_iso(),
    }


def success_envelope(data: Any, *, list_meta: dict | None = None) -> dict:
    meta = _base_meta()
    if list_meta is not None:
        meta.update(list_meta)
        envelope_type = "array"
    elif isinstance(data, list):
        envelope_type = "array"
    else:
        envelope_type = "object"
    return {"meta": meta, "response_type": envelope_type, "data": data}


def error_envelope(error_id: str, message: str) -> dict:
    return {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def respond(data: Any, status: int = 200, *, list_meta: dict | None = None):
    return jsonify(success_envelope(data, list_meta=list_meta)), status
