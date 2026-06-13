"""Public serialization of entities — strips internal-only fields.

Internal-only fields (prefixed with '_') and any helper bookkeeping are removed
before a record is returned in a response envelope.
"""
from __future__ import annotations


def public(rec: dict) -> dict:
    """Return a copy of the record with internal '_' fields removed."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
