"""Shared helpers: pagination parsing, OCC checks, basic validators."""

from datetime import datetime, timedelta, timezone

from flask import request

from config import (
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    MAX_LIMIT,
    MIN_LIMIT,
)
from errors import err_invalid_request, err_version_conflict
from response import parse_iso_utc


def parse_pagination():
    """Pull limit/offset from query params; validate and return (limit, offset)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err_invalid_request(f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}")
    if offset_raw is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Return (slice, total_count)."""
    total = len(items)
    return items[offset : offset + limit], total


def occ_check(obj: dict, body_version):
    """If the body includes 'version', compare against the stored row's version.

    Raises ERR_VERSION_CONFLICT on mismatch. Omitting the field skips the check.
    """
    if body_version is None:
        return
    try:
        v = int(body_version)
    except (TypeError, ValueError):
        raise err_invalid_request("version must be an integer")
    if v != int(obj.get("version", -1)):
        raise err_version_conflict()


def get_json_body():
    """Get a JSON body or {}; raise on parse error."""
    if request.method in ("GET", "DELETE") and not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise err_invalid_request("Request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return body


def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise err_invalid_request(f"Missing required field: {name}")
    return body[name]


def parse_iso_or_400(s, label: str) -> datetime:
    try:
        return parse_iso_utc(s)
    except Exception:
        raise err_invalid_request(f"Invalid ISO 8601 timestamp for {label}")
