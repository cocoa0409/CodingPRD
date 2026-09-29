"""Shared route helpers: existence lookups, OCC guards, transition plumbing."""
from errors import ApiError
from fields import enum_value
from money import D
from store import db

NOT_FOUND = {
    "zones": "ERR_ZONE_NOT_FOUND",
    "varieties": "ERR_VARIETY_NOT_FOUND",
    "crop_cycles": "ERR_CROP_CYCLE_NOT_FOUND",
    "climate_strategies": "ERR_CLIMATE_STRATEGY_NOT_FOUND",
    "fertigation_batches": "ERR_FERTIGATION_BATCH_NOT_FOUND",
    "scouting_observations": "ERR_SCOUTING_OBSERVATION_NOT_FOUND",
    "bio_control_releases": "ERR_BIO_CONTROL_RELEASE_NOT_FOUND",
    "workers": "ERR_WORKER_NOT_FOUND",
    "labor_tasks": "ERR_LABOR_TASK_NOT_FOUND",
    "harvest_lots": "ERR_HARVEST_LOT_NOT_FOUND",
    "retail_programs": "ERR_RETAIL_PROGRAM_NOT_FOUND",
    "commitment_weeks": "ERR_COMMITMENT_WEEK_NOT_FOUND",
    "lot_allocations": "ERR_LOT_ALLOCATION_NOT_FOUND",
}


def fetch(collection, ident):
    record = db[collection].get(ident)
    if record is None:
        raise ApiError(NOT_FOUND[collection])
    return record


def occ(record, expected, error_id):
    if int(expected) != int(record["version"]):
        raise ApiError(
            error_id,
            "expected version %s but the resource is at %s"
            % (expected, record["version"]),
        )


def terminal(status, terminal_set):
    if status in terminal_set:
        raise ApiError("ERR_TERMINAL_STATE", "%s is a terminal state" % status)


def transition(allowed, current, target):
    """allowed: {from_status: (to_status, ...)}"""
    if target not in allowed.get(current, ()):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "cannot move from %s to %s" % (current, target),
        )


def to_status_enum(value, members):
    return enum_value(value, "to_status", members, allow_none=False)


def filter_equals(rows, key, value, caster=None):
    if value is None:
        return rows
    if caster is not None:
        try:
            value = caster(value)
        except (TypeError, ValueError):
            return []
    return [r for r in rows if r.get(key) == value]


def dec(value):
    return D(value)
