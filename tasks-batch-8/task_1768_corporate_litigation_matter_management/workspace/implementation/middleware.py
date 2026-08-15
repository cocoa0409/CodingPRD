"""Auth header extraction, role checking, request body and pagination helpers."""
from flask import request

from errors import ERR_FORBIDDEN_ROLE, ERR_INVALID_REQUEST, ERR_UNAUTHENTICATED, raise_err

ALL_ROLES = (
    "LitigationCounsel",
    "DeputyGeneralCounsel",
    "GeneralCounsel",
    "ChiefFinancialOfficer",
    "BoardCommittee",
    "LegalOperationsAnalyst",
    "FinanceBusinessPartner",
    "StaffUser",
)

READ_SET = (
    "LitigationCounsel",
    "DeputyGeneralCounsel",
    "GeneralCounsel",
    "LegalOperationsAnalyst",
    "FinanceBusinessPartner",
)

READ_SET_CFO = READ_SET + ("ChiefFinancialOfficer",)


def auth(allowed_roles):
    """Validation priorities 1-2: authenticate headers, then authorize role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        role is None
        or role not in ALL_ROLES
        or uid is None
        or not isinstance(uid, str)
        or uid.strip() == ""
    ):
        raise_err(ERR_UNAUTHENTICATED, "Missing or malformed X-User-Role / X-User-ID headers.")
    if role not in allowed_roles:
        raise_err(ERR_FORBIDDEN_ROLE, "Role %s is not authorized for this endpoint." % role)
    return uid, role


def get_body():
    """Return the JSON request body; an absent body is an empty object."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    return data


def pagination_params():
    """Parse limit/offset per PRD 2.3: default 10, min 1, max 100; offset default 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "Query parameter 'limit' must be an integer.")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "Query parameter 'offset' must be an integer.")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def parse_bool_filter(value):
    if value is None:
        return None
    v = value.strip().lower()
    if v == "true":
        return True
    if v == "false":
        return False
    return None


def apply_filters(records, filters):
    """Exact-match equality filters; None values are skipped."""
    out = []
    for rec in records:
        ok = True
        for field, want in filters:
            if want is None:
                continue
            if rec.get(field) != want:
                ok = False
                break
        if ok:
            out.append(rec)
    return out


def paginate(records, sort_key=None):
    """Sort, filter-count and slice a record list; returns (page, limit, offset, total)."""
    limit, offset = pagination_params()
    if sort_key is None:
        ordered = sorted(records, key=lambda r: r.get("_seq", 0))
    else:
        ordered = sorted(records, key=sort_key)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
