"""Shared route helpers: JSON body extraction, entity fetch, filtered serialization."""
from __future__ import annotations
from flask import request

from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from db import db


def get_body() -> dict:
    if request.method in {"POST", "PUT", "PATCH"}:
        if request.content_length and request.content_length > 0:
            try:
                data = request.get_json(force=True, silent=False)
            except Exception:
                raise_error(ERR_INVALID_REQUEST, "Malformed JSON body")
                return {}
            if data is None:
                return {}
            if not isinstance(data, dict):
                raise_error(ERR_INVALID_REQUEST, "Body must be a JSON object")
            return data
        return {}
    return {}


def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise_error(ERR_INVALID_REQUEST, f"Field '{name}' is required")
    return body[name]


def as_int(value, field: str) -> int:
    if isinstance(value, bool):  # bool is a subclass of int; reject
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be an integer")
    if not isinstance(value, int):
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be an integer")
    return value


def fetch(table: dict[str, dict], id_: str) -> dict:
    obj = table.get(id_)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"Resource {id_} not found")
    return obj


# Fields prefixed with _ are internal bookkeeping; strip on the way out.
def clean(entity: dict) -> dict:
    return {k: v for k, v in entity.items() if not k.startswith("_")}
