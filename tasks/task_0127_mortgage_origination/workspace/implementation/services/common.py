"""Common-field helpers: stamp creation/update metadata (PRD §2.4)."""

from utils import new_id, now_utc, to_iso_millis


def init_common(entity: dict) -> dict:
    """Stamp id, created_at, updated_at on a freshly minted entity.

    `version` is set to 1 unless the caller has already supplied a value (e.g., Disclosure
    uses `version` as the per-(application_id, kind) monotonic — server-minted but not OCC).
    """
    now = to_iso_millis(now_utc())
    entity["id"] = new_id()
    entity["created_at"] = now
    entity["updated_at"] = now
    if "version" not in entity:
        entity["version"] = 1
    return entity


def bump(entity: dict) -> None:
    """Bump updated_at and version on a mutation."""
    entity["updated_at"] = to_iso_millis(now_utc())
    entity["version"] = int(entity.get("version", 0)) + 1


def touch(entity: dict) -> None:
    """Bump updated_at only (used for Disclosure, whose `version` is a domain field, not OCC)."""
    entity["updated_at"] = to_iso_millis(now_utc())


def occ_check(entity: dict, body: dict) -> None:
    """Optimistic concurrency check (PRD §2.7).

    If the body contains a `version` key, it must match the resource's current `version`.
    Raises ERR_VERSION_CONFLICT on mismatch.
    """
    if not isinstance(body, dict) or "version" not in body:
        return
    supplied = body["version"]
    if not isinstance(supplied, int) or isinstance(supplied, bool):
        # Treat non-integer version as a mismatch.
        from errors import ERR_VERSION_CONFLICT, raise_error
        raise_error(ERR_VERSION_CONFLICT, "version field must be an integer.")
    if supplied != int(entity.get("version", 0)):
        from errors import ERR_VERSION_CONFLICT, raise_error
        raise_error(ERR_VERSION_CONFLICT, "Stale version on resource.")


def init_append_only(entity: dict) -> dict:
    """Stamp id and created_at only (for append-only entities like RateLockExtension/UDAAPReview)."""
    entity["id"] = new_id()
    entity["created_at"] = to_iso_millis(now_utc())
    return entity
