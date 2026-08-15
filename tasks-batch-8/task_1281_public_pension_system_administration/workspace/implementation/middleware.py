"""Auth header extraction, role checks, entity-backed ownership and shared
request helpers (PRD §2.1, §2.3, §2.8).

Identity scheme:
  X-User-ID + X-User-Role on every request. Seven recognized roles.
  Entity-backed roles: EmployerClerk (X-User-ID == Employer.id),
  Member (== Member.id), SurvivorClaimant (== Beneficiary.id).
"""

from types import SimpleNamespace

from flask import request

from db import store
from errors import err_unauthenticated, err_forbidden, err_invalid_request

ROLES = {
    "FundAdmin",
    "MemberServicesAnalyst",
    "BenefitApprover",
    "MedicalReviewer",
    "EmployerClerk",
    "Member",
    "SurvivorClaimant",
}


def auth():
    """Priority 1: both headers present and the role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err_unauthenticated()
    return SimpleNamespace(user_id=uid, role=role)


def require_roles(ctx, roles):
    """Priority 2: the caller's role must be on the endpoint's list."""
    if ctx.role not in roles:
        raise err_forbidden("Role %s is not permitted for this endpoint" % ctx.role)


# ---------------------------------------------------------------------------
# Entity-backed ownership checks (priority 2)
# ---------------------------------------------------------------------------

def check_member_path(ctx, member_id):
    """Member role may only act on its own member path."""
    if ctx.role == "Member" and ctx.user_id != member_id:
        raise err_forbidden("Member may only act on own records")


def check_member_resource(ctx, owner_member_id):
    """Member role acting on a resource owned by a member (purchase,
    application, benefit, designation)."""
    if ctx.role == "Member" and ctx.user_id != owner_member_id:
        raise err_forbidden("Member may only act on own records")


def check_clerk_employer_path(ctx, employer_id):
    if ctx.role == "EmployerClerk" and ctx.user_id != employer_id:
        raise err_forbidden("Clerk may only act for their own employer")


def check_clerk_employer(ctx, employer_id):
    if ctx.role == "EmployerClerk" and ctx.user_id != employer_id:
        raise err_forbidden("Clerk may only touch their own employer's records")


def check_member_view(ctx, member):
    """Ownership for GET /members/{id} and member-scoped lists."""
    if ctx.role == "Member" and ctx.user_id != member["id"]:
        raise err_forbidden("Member may only view own records")
    elif ctx.role == "EmployerClerk" and ctx.user_id != member["employer_id"]:
        raise err_forbidden("Clerk may only view members of their own employer")
    elif ctx.role == "SurvivorClaimant":
        ben = store.beneficiaries.get(ctx.user_id)
        if ben is None or ben["member_id"] != member["id"]:
            raise err_forbidden("Claimant may only view their own member's records")


def check_benefit_view(ctx, benefit):
    if ctx.role == "Member" and ctx.user_id != benefit["member_id"]:
        raise err_forbidden("Member may only view own benefits")
    elif ctx.role == "SurvivorClaimant":
        ben = store.beneficiaries.get(ctx.user_id)
        if ben is None or ben["member_id"] != benefit["member_id"]:
            raise err_forbidden("Claimant may only view their own member's benefits")


# ---------------------------------------------------------------------------
# Request body / parameter helpers
# ---------------------------------------------------------------------------

def body():
    """JSON request body as a dict; empty/missing body yields {}."""
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def _param(name):
    """Query parameters first (GET), then JSON body as a fallback."""
    if name in request.args:
        return request.args.get(name)
    data = request.get_json(silent=True)
    if isinstance(data, dict) and name in data:
        return data.get(name)
    return None


def pagination():
    """limit (default 10, 1..100) and offset (default 0, >= 0)."""
    raw_limit = _param("limit")
    raw_offset = _param("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if isinstance(raw_limit, float) and not raw_limit.is_integer():
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


# ---------------------------------------------------------------------------
# Field coercion helpers (raise ERR_INVALID_REQUEST on bad shape)
# ---------------------------------------------------------------------------

def req_field(data, name):
    if name not in data or data[name] is None:
        raise err_invalid_request("Missing required field: %s" % name)
    return data[name]


def as_int(value, name):
    if isinstance(value, bool):
        raise err_invalid_request("%s must be an integer" % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise err_invalid_request("%s must be an integer" % name)


def as_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err_invalid_request("%s must be a number" % name)
    return value


def as_str(value, name):
    if not isinstance(value, str) or not value:
        raise err_invalid_request("%s must be a non-empty string" % name)
    return value


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise err_invalid_request(
            "%s must be one of %s" % (name, ", ".join(sorted(allowed)))
        )
    return value


def opt_int(value, name):
    """Optional integer: None passes through, otherwise coerced."""
    if value is None:
        return None
    return as_int(value, name)
