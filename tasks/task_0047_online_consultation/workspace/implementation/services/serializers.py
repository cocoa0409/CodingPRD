"""Resource serializers — strip internal-only fields like `_seq`."""

from __future__ import annotations

_INTERNAL_FIELDS = {"_seq"}


def _clean(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in _INTERNAL_FIELDS}


def serialize(row):
    if row is None:
        return None
    if isinstance(row, list):
        return [_clean(r) for r in row]
    return _clean(row)
