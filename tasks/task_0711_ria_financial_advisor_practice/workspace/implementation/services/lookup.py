"""Existence lookups (PRD §2.5/§2.7 priorities 3 & 4)."""

from db import db
from errors import err


def get_or_404(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return rec


def ref_or_422(collection, _id, label="reference"):
    """Body FK existence: ERR_REFERENCE_NOT_FOUND (422)."""
    rec = collection.get(_id)
    if rec is None:
        raise err("ERR_REFERENCE_NOT_FOUND", f"Referenced {label} does not exist")
    return rec
