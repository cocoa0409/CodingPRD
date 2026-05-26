"""Request payload validation — schema conformance (PRD §2.9 priority 17).

These helpers raise ERR_INVALID_REQUEST (HTTP 400) on type/format/enum/required
violations. Per PRD §2.9, schema checks have the *lowest* priority — they run
only after every domain rule. Tests primarily hit them when the body is
missing a required field at creation, after auth/existence/state pass.
"""
from __future__ import annotations

import re

from errors import invalid_request


def ensure_dict(body) -> dict:
    if body is None or not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    return body


def require_fields(body: dict, names) -> None:
    for n in names:
        if n not in body or body[n] is None:
            raise invalid_request(f"Missing required field: {n!r}")


def reject_extra(body: dict, allowed) -> None:
    extras = set(body.keys()) - set(allowed)
    if extras:
        raise invalid_request(f"Unknown fields: {sorted(extras)!r}")


def check_string(body: dict, name: str, *, pattern: str | None = None,
                 min_len: int = 1, allow_empty: bool = False) -> str:
    v = body.get(name)
    if not isinstance(v, str):
        raise invalid_request(f"Field {name!r} must be a string")
    if not allow_empty and len(v) < min_len:
        raise invalid_request(f"Field {name!r} must be non-empty")
    if pattern and not re.match(pattern, v):
        raise invalid_request(f"Field {name!r} does not match required format")
    return v


def check_int(body: dict, name: str, *, min_val=None, max_val=None) -> int:
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"Field {name!r} must be an integer")
    if min_val is not None and v < min_val:
        raise invalid_request(f"Field {name!r} must be >= {min_val}")
    if max_val is not None and v > max_val:
        raise invalid_request(f"Field {name!r} must be <= {max_val}")
    return v


def check_enum(body: dict, name: str, allowed: set) -> str:
    v = body.get(name)
    if v not in allowed:
        raise invalid_request(f"Field {name!r} must be one of {sorted(allowed)!r}")
    return v
