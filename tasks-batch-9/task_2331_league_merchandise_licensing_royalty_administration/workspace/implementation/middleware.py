"""Auth header extraction, RBAC, ownership scope and pagination (PRD 2.1-2.3, 2.8)."""

from flask import request

import db
from errors import ApiError

ROLE_MANAGER = "LeagueLicensingManager"
ROLE_COMPLIANCE = "MarkComplianceOfficer"
ROLE_FINANCE = "FinanceController"
ROLE_AUDITOR = "RoyaltyAuditor"
ROLE_LICENSEE = "Licensee"
ROLE_CLUB = "ClubRepresentative"
ROLE_AGENT = "PlayerAgent"

ALL_ROLES = [ROLE_MANAGER, ROLE_COMPLIANCE, ROLE_FINANCE, ROLE_AUDITOR,
             ROLE_LICENSEE, ROLE_CLUB, ROLE_AGENT]
OPERATORS = [ROLE_MANAGER, ROLE_COMPLIANCE, ROLE_FINANCE, ROLE_AUDITOR]
ENTITY_ROLES = {ROLE_LICENSEE, ROLE_CLUB, ROLE_AGENT}
ROLE_SET = set(ALL_ROLES)


class Ctx(object):
    __slots__ = ("role", "uid", "body")

    def __init__(self, role, uid, body):
        self.role = role
        self.uid = uid
        self.body = body


def _read_role():
    role = request.headers.get("X-User-Role")
    if role is None:
        role = request.headers.get("X-Role")
    return role


def guard(roles, want_body=None):
    """Rules 1-3 of the global evaluation order, then parse the JSON body."""
    role = _read_role()
    if role is None or role not in ROLE_SET:
        raise ApiError("ERR_UNAUTHORIZED", "Unrecognised or missing X-User-Role.")
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role not authorized for this endpoint.")

    uid = request.headers.get("X-User-ID")
    mutating = request.method in ("POST", "PATCH", "PUT", "DELETE")
    if mutating:
        if uid is None or uid == "":
            raise ApiError("ERR_MISSING_USER_ID", "X-User-ID is required.")

    body = {}
    if want_body is None:
        want_body = mutating
    if want_body:
        body = _json_body()
    return Ctx(role, uid or "", body)


def _json_body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        raise ApiError("ERR_VALIDATION", "Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return parsed


# --------------------------------------------------------------------------- #
# ownership scope (rule 4)                                                    #
# --------------------------------------------------------------------------- #

def scope_licensee(ctx, licensee_id):
    if ctx.role == ROLE_LICENSEE and ctx.uid != licensee_id:
        raise ApiError("ERR_FORBIDDEN_SCOPE", "Resource belongs to another licensee.")


def scope_club(ctx, club_id):
    if ctx.role == ROLE_CLUB and ctx.uid != club_id:
        raise ApiError("ERR_FORBIDDEN_SCOPE", "Resource belongs to another club.")


def scope_player(ctx, player_id):
    if ctx.role == ROLE_AGENT and ctx.uid != player_id:
        raise ApiError("ERR_FORBIDDEN_SCOPE", "Resource belongs to another player.")


def scope_agreement(ctx, agreement):
    if ctx.role == ROLE_LICENSEE:
        scope_licensee(ctx, agreement["licensee_id"])


# --------------------------------------------------------------------------- #
# pagination and filters (rule 10)                                            #
# --------------------------------------------------------------------------- #

def pagination():
    args = request.args
    if "sort" in args:
        raise ApiError("ERR_VALIDATION", "Unknown sort key.")
    limit = 10
    offset = 0
    if "limit" in args:
        limit = _as_int(args.get("limit"), "limit")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100.")
    if "offset" in args:
        offset = _as_int(args.get("offset"), "offset")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be at least 0.")
    return limit, offset


def _as_int(raw, name):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "%s must be an integer." % name)


def filter_str(name):
    value = request.args.get(name)
    return value


def filter_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise ApiError("ERR_VALIDATION", "Invalid %s filter value." % name)
    return value


def filter_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    raise ApiError("ERR_VALIDATION", "%s filter must be true or false." % name)


def paginate(rows, limit, offset):
    ordered = sorted(rows, key=lambda r: r["created_at"])
    total = len(ordered)
    return ordered[offset:offset + limit], total
