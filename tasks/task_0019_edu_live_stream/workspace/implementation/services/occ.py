"""Optimistic concurrency control."""
from errors import raise_api


def check_version(resource, body):
    if body is None:
        return
    if not isinstance(body, dict):
        return
    if "version" in body and body["version"] is not None:
        try:
            req_version = int(body["version"])
        except (TypeError, ValueError):
            raise_api("ERR_STALE_DATA", "version mismatch")
        if req_version != int(resource["version"]):
            raise_api("ERR_STALE_DATA", "version mismatch")
