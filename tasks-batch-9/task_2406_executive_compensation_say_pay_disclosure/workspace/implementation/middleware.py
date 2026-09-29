"""Authentication, role authorisation and pagination (PRD §2.1, §2.3)."""

from flask import request

from errors import ApiError

ROLE_COMP_CONSULTANT = "CompConsultant"
ROLE_CHAIR = "CompCommitteeChair"
ROLE_COUNSEL = "SecuritiesCounsel"
ROLE_IR_LEAD = "InvestorRelationsLead"
ROLE_OFFICER = "NamedExecutiveOfficer"

ALL_ROLES = (
    ROLE_COMP_CONSULTANT,
    ROLE_CHAIR,
    ROLE_COUNSEL,
    ROLE_IR_LEAD,
    ROLE_OFFICER,
)

OPERATOR_ROLES = (ROLE_COMP_CONSULTANT, ROLE_CHAIR, ROLE_COUNSEL, ROLE_IR_LEAD)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

# Pagination parameter names / defaults (scaffold response_envelope).
LIMIT_PARAM = "limit"
OFFSET_PARAM = "offset"
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def authenticate(allowed_roles):
    """Ladder steps 1 and 2: authentication then role authorisation."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


def _positive_int(raw):
    text = str(raw).strip()
    if text == "":
        raise ApiError("ERR_INVALID_REQUEST", "pagination parameters must be integers")
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "pagination parameters must be integers")
    value = int(text)
    return value


def pagination():
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if LIMIT_PARAM in request.args:
        limit = _positive_int(request.args.get(LIMIT_PARAM))
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d" % (LIMIT_MIN, LIMIT_MAX),
            )
    if OFFSET_PARAM in request.args:
        offset = _positive_int(request.args.get(OFFSET_PARAM))
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative")
    return limit, offset


def window(rows, limit, offset):
    return rows[offset: offset + limit]
