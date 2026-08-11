"""The ordered 57-rung validation ladder (PRD 2.6).

Every endpoint walks the same ladder; rungs that do not apply are skipped and
the first rung that fails decides the response.  The helpers here are named
after their rung so a route module reads as a straight-line walk up the ladder.
"""

from flask import request

import clock as clockmod
from constants import (
    CERTIFICATIONS,
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    PAGE_LIMIT_MIN,
    PAGE_OFFSET_DEFAULT,
    ROLES,
)
from errors import NOT_FOUND, ApiError

# ---------------------------------------------------------------------------
# Enum routing (PRD 2.6 rung 5) -- the closed iff-list.
#
# A field routes to ERR_INVALID_ENUM if and only if its NAME appears in
# ENUM_ROUTED_FIELDS below and the supplied value is a string that is not a
# declared member of that field's enumeration.  Everything else routes
# elsewhere; the named exclusions are:
#   * `certifications` members -- NOT on the list, so a bad member is
#     ERR_VALIDATION (rung 4);
#   * `channel` with the well-formed but non-client-writable value "REWORK" --
#     ERR_VALIDATION at the request-shape gate (PRD 3.3);
#   * any listed field supplied with a non-string JSON type -- ERR_VALIDATION
#     at rung 4, because a wrong JSON type is a shape failure, not an enum
#     failure;
#   * numeric fields that parse but fall outside their range --
#     ERR_VALUE_OUT_OF_RANGE (rung 6).
# ---------------------------------------------------------------------------
ENUM_ROUTED_FIELDS = frozenset(
    {
        "account_type",
        "zone_code",
        "billing_mode",
        "cadence",
        "allowed_cadences",
        "item_class",
        "declared_damage_tier",
        "assessed_damage_tier",
        "channel",
        "priority",
        "required_certification",
        "price_tier",
        "min_locker_size",
        "size",
        "grade",
        "requested_grade",
        "method",
        "source",
        "status",
        "billing_status",
        "custody_location",
        "service_status",
        "kind",
    }
)


# ---------------------------------------------------------------------------
# Rung 1 & 2 -- authentication and role authorization.
# ---------------------------------------------------------------------------
class Ctx(object):
    __slots__ = ("user_id", "role", "body", "query")

    def __init__(self, user_id, role, body, query):
        self.user_id = user_id
        self.role = role
        self.body = body
        self.query = query


def begin(*allowed_roles):
    """Walk rungs 1 and 2 and return the request context."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    return Ctx(user_id, role, body, request.args)


# ---------------------------------------------------------------------------
# Rung 3 / 10 -- existence.
# ---------------------------------------------------------------------------
def must_exist(collection, row_id, entity):
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(NOT_FOUND[entity])
    return row


# ---------------------------------------------------------------------------
# Rungs 4-6 -- request shape.
# ---------------------------------------------------------------------------
JSON_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _type_ok(value, declared):
    if declared == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared == "boolean":
        return isinstance(value, bool)
    return isinstance(value, JSON_TYPES[declared])


class Spec(object):
    """Declarative description of one endpoint's request body."""

    def __init__(
        self,
        required=(),
        optional=(),
        enums=None,
        enum_arrays=None,
        ranges=None,
        dates=(),
        times=(),
        periods=(),
        instants=(),
    ):
        self.required = list(required)
        self.optional = list(optional)
        self.enums = dict(enums or {})
        self.enum_arrays = dict(enum_arrays or {})
        self.ranges = dict(ranges or {})
        self.dates = list(dates)
        self.times = list(times)
        self.periods = list(periods)
        self.instants = list(instants)

    def fields(self):
        return self.required + self.optional

    # -- rung 4 ------------------------------------------------------------
    def check_shape(self, body):
        for name, _kind in self.required:
            if name not in body or body[name] is None:
                raise ApiError(
                    "ERR_VALIDATION", "Required field '%s' is missing." % name
                )
        for name, kind in self.fields():
            if name in body and body[name] is not None:
                if not _type_ok(body[name], kind):
                    raise ApiError(
                        "ERR_VALIDATION",
                        "Field '%s' must be of type %s." % (name, kind),
                    )
        # `certifications` is deliberately NOT on the enum-routed list, so a
        # malformed member is a shape failure at this rung.
        if "certifications" in body and isinstance(body.get("certifications"), list):
            members = body["certifications"]
            for member in members:
                if not isinstance(member, str) or member not in CERTIFICATIONS:
                    raise ApiError(
                        "ERR_VALIDATION", "certifications carries an unknown member."
                    )
            if len(set(members)) != len(members):
                raise ApiError(
                    "ERR_VALIDATION", "certifications members must be distinct."
                )
        for name in self.enum_arrays:
            if name in body and isinstance(body.get(name), list):
                members = body[name]
                if not members:
                    raise ApiError("ERR_VALIDATION", "%s must be non-empty." % name)
                for member in members:
                    if not isinstance(member, str):
                        raise ApiError(
                            "ERR_VALIDATION", "%s members must be strings." % name
                        )
                if len(set(members)) != len(members):
                    raise ApiError(
                        "ERR_VALIDATION", "%s members must be distinct." % name
                    )

    # -- rung 5 ------------------------------------------------------------
    def check_enums(self, body):
        for name, members in self.enums.items():
            if name in body and isinstance(body.get(name), str):
                if body[name] not in members:
                    raise ApiError(
                        "ERR_INVALID_ENUM",
                        "Field '%s' carries an undeclared member." % name,
                    )
        for name, members in self.enum_arrays.items():
            if name in body and isinstance(body.get(name), list):
                for member in body[name]:
                    if isinstance(member, str) and member not in members:
                        raise ApiError(
                            "ERR_INVALID_ENUM",
                            "Field '%s' carries an undeclared member." % name,
                        )

    # -- rung 6 ------------------------------------------------------------
    def check_ranges(self, body):
        for name, bounds in self.ranges.items():
            if name in body and body[name] is not None:
                low, high = bounds
                value = body[name]
                if low is not None and value < low:
                    raise ApiError(
                        "ERR_VALUE_OUT_OF_RANGE",
                        "Field '%s' is below its declared minimum." % name,
                    )
                if high is not None and value > high:
                    raise ApiError(
                        "ERR_VALUE_OUT_OF_RANGE",
                        "Field '%s' is above its declared maximum." % name,
                    )
        for name in self.dates:
            if name in body and body[name] is not None:
                if clockmod.parse_date(body[name]) is None:
                    raise ApiError(
                        "ERR_VALUE_OUT_OF_RANGE",
                        "Field '%s' is not an ISO calendar date." % name,
                    )
        for name in self.times:
            if name in body and body[name] is not None:
                if clockmod.parse_hhmm(body[name]) is None:
                    raise ApiError(
                        "ERR_VALUE_OUT_OF_RANGE",
                        "Field '%s' is not an HH:MM time." % name,
                    )
        for name in self.periods:
            if name in body and body[name] is not None:
                if clockmod.parse_period(body[name]) is None:
                    raise ApiError(
                        "ERR_VALUE_OUT_OF_RANGE",
                        "Field '%s' is not a YYYY-MM period." % name,
                    )
        for name in self.instants:
            if name in body and body[name] is not None:
                if clockmod.parse_instant(body[name]) is None:
                    raise ApiError(
                        "ERR_VALUE_OUT_OF_RANGE",
                        "Field '%s' is not an ISO 8601 instant." % name,
                    )

    def validate(self, body, extra_shape=None):
        """Rungs 4, 5 and 6 in their pinned internal order."""
        self.check_shape(body)
        if extra_shape is not None:
            extra_shape(body)
        self.check_enums(body)
        self.check_ranges(body)


# ---------------------------------------------------------------------------
# Rung 5 for query filters, then rung 7 for pagination.
# ---------------------------------------------------------------------------
def check_query_enums(query, enums):
    for name, members in enums.items():
        raw = query.get(name)
        if raw is not None and raw not in members:
            raise ApiError(
                "ERR_INVALID_ENUM", "Filter '%s' carries an undeclared member." % name
            )


def check_query_integers(query, names):
    values = {}
    for name in names:
        raw = query.get(name)
        if raw is None:
            values[name] = None
            continue
        try:
            values[name] = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ApiError(
                "ERR_VALUE_OUT_OF_RANGE", "Filter '%s' must be an integer." % name
            )
    return values


def pagination(query):
    """Rung 7."""
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = query.get("limit")
    raw_offset = query.get("offset")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if str(raw_limit).strip() != str(limit):
            raise ApiError("ERR_INVALID_PAGINATION")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError("ERR_INVALID_PAGINATION")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if str(raw_offset).strip() != str(offset):
            raise ApiError("ERR_INVALID_PAGINATION")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset : offset + limit], total
