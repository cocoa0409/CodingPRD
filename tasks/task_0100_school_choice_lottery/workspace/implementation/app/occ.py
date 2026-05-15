"""Optimistic concurrency check — PRD §2.6."""
from .errors import APIError


def check_version(record: dict, body: dict, field: str = "version") -> None:
    """If body contains version, it must match record['version']. Else skip."""
    if body is None:
        return
    if field not in body or body[field] is None:
        return
    provided = body[field]
    if not isinstance(provided, int) or isinstance(provided, bool):
        raise APIError("ERR_VALIDATION", "version must be an integer")
    if provided != record.get("version"):
        raise APIError("ERR_VERSION_MISMATCH",
                       f"version mismatch (provided {provided}, current {record.get('version')})")
