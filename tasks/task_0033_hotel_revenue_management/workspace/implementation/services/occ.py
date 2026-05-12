"""Optimistic concurrency helper."""
from errors import err


def check_version(body: dict, entity: dict):
    """If body has 'version', it must equal entity['version']; else raise ERR_VERSION_CONFLICT."""
    if not isinstance(body, dict):
        return
    if "version" not in body or body["version"] is None:
        return
    v = body["version"]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_INPUT", "version must be an integer")
    if v != entity.get("version"):
        raise err("ERR_VERSION_CONFLICT", "version does not match current entity version")
