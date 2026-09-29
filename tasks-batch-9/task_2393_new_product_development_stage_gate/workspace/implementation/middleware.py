"""Authentication, role authorisation, pagination, filtering and ordering.

Bands 1 and 2 of PRD §2.5 live here and, critically, they run *before* any
path identifier is resolved: an unauthenticated request naming a non-existent
resource answers 401 and a wrong-role one answers 403 — never 404.
"""

import re

from flask import request

from errors import ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, ERR_INVALID_REQUEST, fail

ALL_ROLES = (
    "PortfolioAdmin",
    "InnovationLead",
    "GateChair",
    "FunctionalReviewer",
    "RegulatoryApprover",
    "RnDLead",
    "SalesAccountManager",
)

_INT_RE = re.compile(r"^[+-]?\d+$")


def authenticate(*allowed_roles):
    """Return the acting opaque ``X-User-ID`` after enforcing bands 1 and 2.

    ``X-User-Role`` is the header named by the PRD; ``X-Role`` is accepted as a
    synonym because the seed tables spell it that way.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if role is None or role == "":
        role = request.headers.get("X-Role")
    if not user_id or not role:
        fail(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role headers are required.")
    if role not in allowed_roles:
        fail(ERR_UNAUTHORIZED, "Role %s may not perform this operation." % role)
    return user_id


def reader():
    """Every one of the seven roles may call every read endpoint."""
    return authenticate(*ALL_ROLES)


# ---------------------------------------------------------------------------
# pagination
# ---------------------------------------------------------------------------
def pagination():
    limit, offset = 10, 0
    raw = request.args.get("limit")
    if raw is not None:
        if not _INT_RE.match(raw.strip()):
            fail(ERR_INVALID_REQUEST, "limit must be an integer.")
        limit = int(raw)
        if limit < 1 or limit > 100:
            fail(ERR_INVALID_REQUEST, "limit must be between 1 and 100.")
    raw = request.args.get("offset")
    if raw is not None:
        if not _INT_RE.match(raw.strip()):
            fail(ERR_INVALID_REQUEST, "offset must be an integer.")
        offset = int(raw)
        if offset < 0:
            fail(ERR_INVALID_REQUEST, "offset may not be negative.")
    return limit, offset


def page(rows_list):
    limit, offset = pagination()
    total = len(rows_list)
    return rows_list[offset:offset + limit], limit, offset, total


# ---------------------------------------------------------------------------
# equality filters
# ---------------------------------------------------------------------------
def _matches(stored, wanted):
    if stored is None:
        return wanted in ("", "null", "None")
    if isinstance(stored, bool):
        return str(stored).lower() == wanted.strip().lower()
    if isinstance(stored, int):
        if not _INT_RE.match(wanted.strip()):
            return False
        return stored == int(wanted)
    return str(stored) == wanted


def apply_filters(rows_list, fields):
    """Filter ``rows_list`` by the query parameters named in ``fields``.

    ``fields`` maps query-parameter name -> stored field name.
    """
    out = rows_list
    for param, field in fields.items():
        if param in request.args:
            wanted = request.args.get(param)
            out = [r for r in out if _matches(r.get(field), wanted)]
    return out


# ---------------------------------------------------------------------------
# ordering
# ---------------------------------------------------------------------------
def order(rows_list, keys=()):
    """Order rows by ``keys`` (most significant first) then ``created_at`` ASC.

    ``keys`` is a sequence of ``(extractor, descending)`` pairs. Sorting is
    applied least-significant-first with a stable sort, so the composite order
    is exactly the declared one. ``id`` is never an ordering key.
    """
    out = sorted(rows_list, key=lambda r: r["_seq"])
    for extractor, descending in reversed(list(keys)):
        out = sorted(out, key=extractor, reverse=descending)
    return out


def by(field):
    return lambda r: r[field]
