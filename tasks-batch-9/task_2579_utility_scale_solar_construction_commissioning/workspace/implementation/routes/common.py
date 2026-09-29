"""Helpers shared by the domain blueprints."""

import envelope
import store
import validate
from errors import fail, invalid


def paginate(rows):
    """Apply limit/offset AFTER filtering and emit the array envelope."""
    limit, offset = validate.page()
    total = len(rows)
    return envelope.collection(rows[offset : offset + limit], limit, offset, total)


def filter_eq(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


def unique_check(collection, scope_field, scope_value, field, value):
    """No dedicated error id exists for duplicates, so this is a 400."""
    for row in collection.values():
        if row.get(scope_field) == scope_value and row.get(field) == value:
            invalid("%s '%s' already exists in this scope" % (field, value))


def project_substation_energized(project_id):
    for substation in store.substations.values():
        if substation["project_id"] == project_id and substation["status"] == "ENERGIZED":
            return True
    return False


def require_same_project(child_project_id, project_id):
    if child_project_id != project_id:
        fail("ERR_CROSS_PROJECT_REFERENCE")
