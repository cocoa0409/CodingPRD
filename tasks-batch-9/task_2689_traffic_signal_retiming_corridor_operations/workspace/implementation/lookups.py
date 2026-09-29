"""Path- and body-identifier resolution plus small list helpers."""

import response
import validators
from db import db
from errors import fail

TERMINAL_PROJECT_STATUSES = ("CLOSED", "ABANDONED")


def _get(table, key, error_id):
    row = table.get(key) if isinstance(key, str) else None
    if row is None:
        fail(error_id)
    return row


def intersection(intersection_id):
    return _get(db.intersections, intersection_id, "ERR_INTERSECTION_NOT_FOUND")


def corridor(corridor_id):
    return _get(db.corridors, corridor_id, "ERR_CORRIDOR_NOT_FOUND")


def requester(requester_id):
    return _get(db.requesters, requester_id, "ERR_REQUESTER_NOT_FOUND")


def complaint(complaint_id):
    return _get(db.complaints, complaint_id, "ERR_COMPLAINT_NOT_FOUND")


def project(project_id):
    return _get(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")


def plan(plan_id):
    return _get(db.plans, plan_id, "ERR_TIMING_PLAN_NOT_FOUND")


def phase_split(split_id):
    return _get(db.phase_splits, split_id, "ERR_PHASE_SPLIT_NOT_FOUND")


def ped_check(check_id):
    return _get(db.ped_checks, check_id, "ERR_PED_CHECK_NOT_FOUND")


def priority_config(config_id):
    return _get(db.priority_configs, config_id, "ERR_PRIORITY_CONFIG_NOT_FOUND")


def observation(observation_id):
    return _get(db.observations, observation_id, "ERR_OBSERVATION_NOT_FOUND")


def evaluation(evaluation_id):
    return _get(db.evaluations, evaluation_id, "ERR_EVALUATION_NOT_FOUND")


def not_terminal(project_row):
    """PRD 3.10: ERR_PROJECT_TERMINAL guards any write against a finished project."""
    if project_row["status"] in TERMINAL_PROJECT_STATUSES:
        fail("ERR_PROJECT_TERMINAL")
    return project_row


def apply_filter(rows, field, arg_name=None):
    """Filter rows on an exact string match of a query parameter, when supplied."""
    value = validators.filter_arg(arg_name or field)
    if value is None:
        return rows
    return [r for r in rows if str(r.get(field)) == value]


def listing(rows, serializer):
    limit, offset = validators.pagination()
    window, total = response.paginate(rows, limit, offset)
    return response.ok_list([serializer(r) for r in window], limit, offset, total)
