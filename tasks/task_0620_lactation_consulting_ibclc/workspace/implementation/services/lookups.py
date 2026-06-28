"""Resource lookup helpers and client-derived-field recompute logic."""
import db
from errors import (
    err,
    ERR_RESOURCE_NOT_FOUND,
    ERR_REFERENCED_RESOURCE_NOT_FOUND,
)


def get_or_404(collection, rid):
    """Path-id resolution (PRD §2.6): ERR_RESOURCE_NOT_FOUND if absent."""
    record = collection.get(rid)
    if record is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Resource not found: %s" % rid)
    return record


def get_fk_or_404(collection, rid):
    """Body foreign-key resolution (PRD §2.6): ERR_REFERENCED_RESOURCE_NOT_FOUND
    if absent."""
    record = collection.get(rid)
    if record is None:
        raise err(ERR_REFERENCED_RESOURCE_NOT_FOUND,
                  "Referenced resource not found: %s" % rid)
    return record


def recompute_credits_remaining(client):
    """package_credits_remaining = total - consumed, never negative
    (PRD §3.2)."""
    remaining = client["package_credits_total"] - client["package_credits_consumed"]
    if remaining < 0:
        remaining = 0
    client["package_credits_remaining"] = remaining
