"""Common validation helpers."""
from __future__ import annotations

import re
from typing import Any, Optional

from ..clock import parse_iso
from ..errors import ApiError


COURSE_CODE_PATTERN = re.compile(r"^[A-Z]{2,6}-[0-9]{3,5}$")
TAG_PATTERN = re.compile(r"^[a-z0-9-]+$")
IPV4_PATTERN = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")


def require_str(body: dict, field: str, min_len: int = 1, max_len: int | None = None) -> str:
    value = body.get(field)
    if not isinstance(value, str) or len(value) < min_len:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"Field {field!r} must be a non-empty string.", http_status=422)
    if max_len is not None and len(value) > max_len:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"Field {field!r} too long.", http_status=422)
    return value


def require_iso(body: dict, field: str):
    value = body.get(field)
    if value is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"Field {field!r} is required.", http_status=422)
    try:
        return parse_iso(value)
    except ValueError as exc:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"Field {field!r}: {exc}", http_status=422)


def validate_ipv4_in_private_cidrs(ip: str) -> bool:
    """Returns True if ip is in 10.0.0.0/8 or 192.168.0.0/16."""
    m = IPV4_PATTERN.match(ip or "")
    if not m:
        return False
    octets = [int(o) for o in m.groups()]
    if any(o < 0 or o > 255 for o in octets):
        return False
    if octets[0] == 10:
        return True
    if octets[0] == 192 and octets[1] == 168:
        return True
    return False


def normalize_tag_list(tags: Any, max_count: int = 10) -> list[str]:
    if tags is None:
        return []
    if not isinstance(tags, list):
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "tags must be a list.", http_status=422)
    if len(tags) > max_count:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"too many tags (>{max_count}).", http_status=422)
    out = []
    for t in tags:
        if not isinstance(t, str):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "tag must be a string.", http_status=422)
        if not (2 <= len(t) <= 32) or not TAG_PATTERN.match(t):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", f"invalid tag {t!r}.", http_status=422)
        out.append(t)
    return out
