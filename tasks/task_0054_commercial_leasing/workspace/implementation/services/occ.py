"""Optimistic concurrency control."""
from errors import err


def check_version(body: dict, current: dict) -> None:
    """If body contains 'version', compare with current['version']."""
    if not isinstance(body, dict):
        return
    if "version" in body and body["version"] is not None:
        provided = body["version"]
        stored = current.get("version")
        if provided != stored:
            raise err("ERR_VERSION_MISMATCH",
                      f"Version mismatch: expected {stored}, got {provided}")
