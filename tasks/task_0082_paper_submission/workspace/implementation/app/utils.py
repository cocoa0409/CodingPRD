"""Cross-cutting helpers: pagination, JSON body parsing, version checks."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from flask import request

from .errors import api_error


_TOPIC_TAG_RE = re.compile(r"^[a-z0-9_]+$")
_ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{4}$")


def get_json_body() -> dict:
    """Return the parsed JSON body as a dict; empty body returns {}."""
    if request.method in ("GET", "DELETE") and not request.data:
        return {}
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise api_error("ERR_VALIDATION", "Request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise api_error("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def require_str(body: dict, key: str) -> str:
    val = body.get(key)
    if not isinstance(val, str) or val == "":
        raise api_error("ERR_VALIDATION", f"Field '{key}' is required and must be a non-empty string")
    return val


def optional_str(body: dict, key: str, default: str | None = None) -> str | None:
    val = body.get(key, default)
    if val is None:
        return default
    if not isinstance(val, str):
        raise api_error("ERR_VALIDATION", f"Field '{key}' must be a string")
    return val


def optional_list(body: dict, key: str) -> list:
    val = body.get(key, [])
    if val is None:
        return []
    if not isinstance(val, list):
        raise api_error("ERR_VALIDATION", f"Field '{key}' must be an array")
    return val


def parse_pagination():
    """Read limit/offset from query string, applying defaults & bounds."""
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        raise api_error("ERR_VALIDATION", "limit must be an integer")
    try:
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise api_error("ERR_VALIDATION", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise api_error("ERR_VALIDATION", "limit must be in [1, 100]")
    if offset < 0:
        raise api_error("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def page_slice(items: list, limit: int, offset: int) -> tuple[list, int]:
    total = len(items)
    return items[offset : offset + limit], total


def check_version(body: dict, stored: dict, key: str = "version") -> None:
    """If body contains `version`, enforce equality with stored.version.

    Per PRD §2.6, mismatch (stale, ahead, or negative) -> ERR_VERSION_CONFLICT.
    """
    if key in body and body[key] is not None:
        supplied = body[key]
        if not isinstance(supplied, int):
            raise api_error("ERR_VERSION_CONFLICT", "version must equal stored version")
        if supplied != stored.get("version"):
            raise api_error("ERR_VERSION_CONFLICT", "Supplied version does not match stored version")


def validate_topic_tag(tag: str) -> None:
    if not _TOPIC_TAG_RE.match(tag):
        raise api_error("ERR_VALIDATION", "topic_tag must match ^[a-z0-9_]+$")


def validate_orcid(orcid_id: str) -> None:
    if not _ORCID_RE.match(orcid_id):
        raise api_error("ERR_VALIDATION", "orcid_id must match the 0000-0000-0000-0000 shape")


def parse_iso_datetime(value: str) -> datetime:
    """Parse an ISO 8601 datetime string; tolerate Z suffix."""
    if not isinstance(value, str):
        raise api_error("ERR_VALIDATION", "Datetime field must be a string")
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise api_error("ERR_VALIDATION", f"Invalid ISO 8601 datetime: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_or_none(value: str | None) -> datetime | None:
    if value is None:
        return None
    return parse_iso_datetime(value)
