"""The validation ladder of PRD section 2.9.

Authentication (ERR_UNAUTHENTICATED) -> role authorization (ERR_FORBIDDEN) ->
existence, left to right (ERR_NOT_FOUND) -> Producer-role ownership scoping
(ERR_FORBIDDEN) -> state tiers -> business gates.  Requests malformed in
themselves (missing required field, invalid enum value, malformed datetime,
non-positive credit_hours, expiration_date not strictly after issue_date,
uniqueness collisions) are rejected with ERR_INVALID_REQUEST.
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request

from . import constants as K
from .clock import parse_instant
from .errors import fail
from .store import db


class Ctx(object):
    def __init__(self, role, user_id, body):
        self.role = role
        self.user_id = user_id
        self.body = body

    def get(self, name, default=None):
        value = self.body.get(name)
        return default if value is None else value


def _body():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {}
    return payload


def authorize(*allowed_roles):
    """Rung 1 (authentication, 401) then rung 2 (role authorization, 403)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in K.ROLES:
        fail("ERR_UNAUTHENTICATED", "Missing or invalid X-User-ID / X-User-Role headers.")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN", "Role {} may not call this endpoint.".format(role))
    return Ctx(role, user_id, _body())


# -- rung 4: existence -----------------------------------------------------

def resolve(collection, row_id):
    row = getattr(db, collection).get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail("ERR_NOT_FOUND", "No such resource: {}.".format(row_id))
    return row


def resolve_body_ref(ctx, field, collection):
    value = ctx.body.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '{}' must be a string id.".format(field))
    return resolve(collection, value)


# -- rung 5: Producer-role ownership scoping --------------------------------

def producer_scope(ctx, producer_id):
    """A Producer caller may touch only records whose producer link is their id."""
    if ctx.role == "Producer" and ctx.user_id != producer_id:
        fail("ERR_FORBIDDEN", "Producer may only access their own records.")


# -- malformed-request field validation (ERR_INVALID_REQUEST) ---------------

def req_str(body, name):
    value = body.get(name)
    if not isinstance(value, str) or value == "":
        fail("ERR_INVALID_REQUEST", "Field '{}' is required and must be a string.".format(name))
    return value


def opt_str(body, name):
    value = body.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '{}' must be a string.".format(name))
    return value


def req_int(body, name):
    value = body.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '{}' is required and must be an integer.".format(name))
    return value


def req_enum(body, name, allowed):
    value = body.get(name)
    if not isinstance(value, str) or value not in allowed:
        fail(
            "ERR_INVALID_REQUEST",
            "Field '{}' must be one of {}.".format(name, ", ".join(allowed)),
        )
    return value


def req_dt(body, name):
    value = body.get(name)
    parsed = parse_instant(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '{}' must be an ISO 8601 datetime.".format(name))
    return parsed


def opt_dt(body, name):
    value = body.get(name)
    if value is None:
        return None
    parsed = parse_instant(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '{}' must be an ISO 8601 datetime.".format(name))
    return parsed


def req_number(body, name):
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '{}' is required and must be a number.".format(name))
    try:
        return Decimal(str(value))
    except InvalidOperation:
        fail("ERR_INVALID_REQUEST", "Field '{}' must be a number.".format(name))


def opt_number(body, name, default):
    if body.get(name) is None:
        return default
    value = req_number(body, name)
    return value


def req_hours(body, name):
    """CE credit hours: > 0, rounded half-up to one decimal place on input."""
    value = req_number(body, name)
    rounded = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if rounded <= 0:
        fail("ERR_INVALID_REQUEST", "Field '{}' must be greater than zero.".format(name))
    return rounded


def req_loa_list(body, name):
    value = body.get(name)
    if not isinstance(value, list) or len(value) == 0:
        fail(
            "ERR_INVALID_REQUEST",
            "Field '{}' must be a non-empty array of lines of authority.".format(name),
        )
    for element in value:
        if not isinstance(element, str) or element not in K.LOAS:
            fail(
                "ERR_INVALID_REQUEST",
                "Field '{}' members must be drawn from {}.".format(name, ", ".join(K.LOAS)),
            )
    return list(value)


def subject_ids(ctx):
    """The §2.6 subject pair: validates types; xor itself is a later rung."""
    producer_id = ctx.body.get("producer_id")
    agency_id = ctx.body.get("agency_id")
    if producer_id is not None and not isinstance(producer_id, str):
        fail("ERR_INVALID_REQUEST", "Field 'producer_id' must be a string id.")
    if agency_id is not None and not isinstance(agency_id, str):
        fail("ERR_INVALID_REQUEST", "Field 'agency_id' must be a string id.")
    return producer_id, agency_id


def resolve_subject_refs(ctx, producer_id, agency_id):
    """Existence of body FK references, validated left to right (rung 4)."""
    if producer_id is not None:
        resolve("producers", producer_id)
    if agency_id is not None:
        resolve("agencies", agency_id)


def require_exactly_one_subject(producer_id, agency_id):
    if (producer_id is None) == (agency_id is None):
        fail(
            "ERR_LICENSE_SUBJECT_CONFLICT",
            "Exactly one of producer_id / agency_id must be set.",
        )


def subject_of(row):
    """Return (field, id) naming the row's licensing subject."""
    if row.get("producer_id") is not None:
        return "producer_id", row["producer_id"]
    return "agency_id", row.get("agency_id")
