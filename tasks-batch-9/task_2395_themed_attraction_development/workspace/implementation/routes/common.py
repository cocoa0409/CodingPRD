"""Shared helpers used by every route module."""

import store
import validate as V
from errors import ApiError


def no_body():
    """Endpoints declaring `input: []` still reject any unknown body field."""
    V.validate_body(V.read_body(), [])


def body(*fields):
    return V.validate_body(V.read_body(), list(fields))


def check_project_version(project, expected):
    if expected != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION", 412)


def check_package_version(package, expected):
    if expected != package["version"]:
        raise ApiError("ERR_STALE_PACKAGE_VERSION", 412)


def check_ride_system_version(system, expected):
    if expected != system["version"]:
        raise ApiError("ERR_STALE_RIDE_SYSTEM_VERSION", 412)


def state(row, allowed, error_id):
    if row["status"] not in allowed:
        raise ApiError(error_id, 409)


def page(rows, limit, offset):
    """Slice `rows` and return (public window, total_count)."""
    total = len(rows)
    window = rows[offset : offset + limit]
    return store.public_list(window), total
