"""Shared helpers — common-fields stamping, semver parsing, validation utilities."""

from clock import now, iso
from errors import APIError, version_conflict, invalid_request


def stamp_create():
    n = now()
    return {
        "created_at": iso(n),
        "updated_at": iso(n),
        "version": 0,
    }


def stamp_update(record):
    n = now()
    record["updated_at"] = iso(n)
    record["version"] = record.get("version", 0) + 1


def check_version(record, payload_version):
    """OCC: when caller supplies version, must match. Omit -> skip."""
    if payload_version is None:
        return
    try:
        v = int(payload_version)
    except (TypeError, ValueError):
        raise invalid_request("version must be an integer")
    if v != record.get("version", 0):
        raise version_conflict(f"version mismatch: expected {record.get('version')}, got {v}")


def semver_tuple(s):
    """Lexicographic compare by parts, parsing numeric where possible."""
    if s is None:
        return ()
    parts = []
    for p in str(s).split("."):
        try:
            parts.append(int(p))
        except (TypeError, ValueError):
            parts.append(p)
    return tuple(parts)


def semver_ge(a, b):
    return semver_tuple(a) >= semver_tuple(b)


def require_field(payload, name):
    if not isinstance(payload, dict):
        raise invalid_request("Body must be a JSON object")
    if name not in payload or payload[name] in (None, ""):
        raise invalid_request(f"Missing required field: {name}")
    return payload[name]


def opt_field(payload, name, default=None):
    if not isinstance(payload, dict):
        return default
    return payload.get(name, default)
