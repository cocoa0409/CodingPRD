"""Optimistic concurrency control helper (PRD §2.10)."""

from errors import AppError, ERR_STALE_DATA


def check_version(body: dict, resource: dict) -> None:
    """If body provides 'version', it must equal resource['version'].

    Skipped when body has no version key.
    """
    if not isinstance(body, dict):
        return
    if "version" not in body or body["version"] is None:
        return
    try:
        provided = int(body["version"])
    except (TypeError, ValueError):
        raise AppError(ERR_STALE_DATA, "Stale version supplied.", 409)
    current = int(resource.get("version", 0))
    if provided != current:
        raise AppError(ERR_STALE_DATA, "Stale version supplied.", 409)
