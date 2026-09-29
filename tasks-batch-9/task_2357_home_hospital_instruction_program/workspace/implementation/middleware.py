"""Authentication, authorization and the request pipeline (PRD §2.1, §2.6)."""

import functools

from flask import g, request

import db
import response
from errors import ApiError
from validation import validate_body, validate_query

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLES = (
    "ProgramAdministrator",
    "CaseManager",
    "NurseReviewer",
    "HomeboundTeacher",
    "ClassroomTeacher",
)


class Result(object):
    """What a handler returns: the payload kind plus its value."""

    __slots__ = ("kind", "value", "page")

    def __init__(self, kind, value, page=None):
        self.kind = kind
        self.value = value
        self.page = page


def obj(row):
    return Result("row", row)


def arr(rows, page):
    return Result("rows", rows, page)


def raw(payload):
    return Result("raw", payload)


def empty():
    return Result("raw", {})


def authenticate(roles):
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED")
    g.user_id = user_id
    g.role = role


def endpoint(roles, body=None, query=None, status=200):
    """Wire tiers 1-3 and the flush/serialize step around a handler."""

    def decorator(handler):
        @functools.wraps(handler)
        def wrapper(**kwargs):
            db.begin_request()
            authenticate(roles)                 # tier 1 + tier 2
            g.body = validate_body(body)        # tier 3 (body)
            g.query = validate_query(query)     # tier 3 (query)
            result = handler(**kwargs)
            db.flush()
            if result.kind == "row":
                return response.success(db.public(result.value), "object", None, status)
            if result.kind == "rows":
                data = [db.public(r) for r in result.value]
                return response.success(data, "array", result.page, status)
            return response.success(result.value, "object", None, status)

        return wrapper

    return decorator


def body():
    return g.body


def query():
    return g.query


def user_id():
    return g.user_id


def role():
    return g.role
