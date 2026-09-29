"""Authentication, role checking and pagination parsing (PRD 2.1, 2.3, 2.10)."""
from flask import request

from errors import fail

ROLE_SERIES_PROMOTER = "SeriesPromoter"
ROLE_VENUE_MANAGER = "VenueManager"
ROLE_COMPETITOR_TEAM = "CompetitorTeam"
ROLE_SAFETY_OFFICIAL = "SafetyOfficial"
ROLE_TICKETING_MANAGER = "TicketingManager"
ROLE_SPONSOR_REP = "SponsorRep"
ROLE_FINANCE_CONTROLLER = "FinanceController"

ALL_ROLES = (
    ROLE_SERIES_PROMOTER,
    ROLE_VENUE_MANAGER,
    ROLE_COMPETITOR_TEAM,
    ROLE_SAFETY_OFFICIAL,
    ROLE_TICKETING_MANAGER,
    ROLE_SPONSOR_REP,
    ROLE_FINANCE_CONTROLLER,
)


def auth(*allowed_roles):
    """Ladder step 1 (ERR_UNAUTHENTICATED) then step 2 (ERR_UNAUTHORIZED)."""
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id.strip() == "":
        fail("ERR_UNAUTHENTICATED")
    role = request.headers.get("X-User-Role")
    if role is None or role.strip() == "" or role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")
    return user_id, role


def _parse_int_param(raw, name):
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    value = int(text)
    return value


def pagination():
    limit = _parse_int_param(request.args.get("limit"), "limit")
    offset = _parse_int_param(request.args.get("offset"), "offset")
    if limit is None:
        limit = 10
    elif limit < 1 or limit > 100:
        fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset is None:
        offset = 0
    elif offset < 0:
        fail("ERR_INVALID_REQUEST", "offset must not be negative")
    return limit, offset


def enum_filter(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return raw


def string_filter(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
