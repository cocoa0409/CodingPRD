"""Optimistic concurrency control helper."""
import errors as E


def check_version(record: dict, body: dict):
    """If body carries 'version', it must equal record['version']."""
    if not isinstance(body, dict):
        return
    if "version" in body and body["version"] is not None:
        v = body["version"]
        if not isinstance(v, int) or isinstance(v, bool):
            E.version_mismatch("version must be an integer")
        if v != record.get("version", 1):
            E.version_mismatch("Stale version")
