"""Response envelope and metadata helpers."""
import random
import string
from typing import Any

from flask import jsonify

from .clock import now_iso


def gen_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return f"req_{suffix}"


def build_meta(pagination: dict | None = None) -> dict:
    meta = {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data: Any, status: int = 200, pagination: dict | None = None):
    is_array = isinstance(data, list)
    body = {
        "meta": build_meta(pagination),
        "response_type": "array" if is_array else "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status
