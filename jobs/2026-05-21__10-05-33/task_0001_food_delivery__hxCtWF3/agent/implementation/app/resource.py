"""Helpers for versioned resources: stamping created/updated/version, OCC check."""
from .clock import format_iso
from .errors import fail
from .ids import new_uuid


def stamp_new(versioned: bool = True) -> dict:
    """Return the audit fields for a freshly created resource."""
    from .server import clock
    now = format_iso(clock.now())
    base = {"id": new_uuid(), "created_at": now}
    if versioned:
        base["updated_at"] = now
        base["version"] = 1
    return base


def bump(resource: dict) -> None:
    """Touch updated_at and increment version. Mutates in place."""
    from .server import clock
    resource["updated_at"] = format_iso(clock.now())
    resource["version"] = resource.get("version", 1) + 1


def check_occ(resource: dict, body: dict) -> None:
    """If body has 'version', it must match resource['version']."""
    if "version" not in body or body["version"] is None:
        return
    if body["version"] != resource.get("version"):
        raise fail("ERR_VERSION_CONFLICT")
