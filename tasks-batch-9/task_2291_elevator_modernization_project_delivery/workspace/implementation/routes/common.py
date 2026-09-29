"""Shared helpers for the route modules."""

from db import ordered
from errors import ApiError
from middleware import enforce_scope, scope_filter
from response import list_response, object_response
from validation import enum_query, int_query, pagination

ALL_ROLES = [
    "ProjectManager",
    "SurveyTechnician",
    "BuildingRepresentative",
    "AHJInspector",
    "ServiceManager",
    "SystemOperator",
]


def require(row):
    if row is None:
        raise ApiError("ERR_NOT_FOUND")
    return row


def fetch(collection, row_id):
    return require(collection.get(row_id))


def read_one(row, serializer, project):
    enforce_scope(project)
    return object_response(serializer(row))


def paged(rows, serializer, project_resolver=None):
    rows = ordered(rows)
    rows = scope_filter(rows, project_resolver)
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serializer(r) for r in page], limit, offset, total)


def eq_filter(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


def str_query(name):
    from flask import request

    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


__all__ = [
    "ALL_ROLES",
    "require",
    "fetch",
    "read_one",
    "paged",
    "eq_filter",
    "str_query",
    "enum_query",
    "int_query",
    "pagination",
    "object_response",
    "list_response",
    "enforce_scope",
]
