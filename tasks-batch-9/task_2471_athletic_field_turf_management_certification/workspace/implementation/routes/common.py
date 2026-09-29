"""Shared list-endpoint plumbing (PRD 2.3)."""

from flask import request

import response
import validate
from db import by_creation


def _matches(value, raw):
    if isinstance(value, bool):
        lowered = raw.strip().lower()
        if lowered not in ("true", "false"):
            return False
        return value is (lowered == "true")
    if value is None:
        return False
    if isinstance(value, str):
        return value == raw
    return str(value) == raw


def filtered(collection, spec):
    """Additive equality filters; an unrecognised value simply matches nothing."""
    rows = list(collection.values())
    for param, key in spec.items():
        raw = request.args.get(param, None)
        if raw is None:
            continue
        rows = [r for r in rows if _matches(r.get(key), raw)]
    return by_creation(rows)


def listing(collection, spec):
    limit, offset = validate.pagination()
    rows = filtered(collection, spec)
    page = rows[offset:offset + limit]
    return response.ok_list(page, limit, offset, len(rows))
