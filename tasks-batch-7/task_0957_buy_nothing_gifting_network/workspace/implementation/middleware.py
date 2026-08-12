import re

from flask import request

import db
from errors import raise_err
from utils import parse_iso

ROLES = {"Anonymous", "Member", "GroupModerator", "PlatformAdmin"}
ENTITY_ROLES = {"Member", "GroupModerator"}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ZIP_RE = re.compile(r"^\d{5}$")

MISSING = object()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def get_auth():
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise_err("ERR_UNAUTHENTICATED", "missing or malformed X-User-Role header")
    uid = request.headers.get("X-User-ID")
    if role in ENTITY_ROLES and not uid:
        raise_err("ERR_UNAUTHENTICATED", "X-User-ID header is required for this role")
    return role, uid


def require_role(role, allowed):
    if role not in allowed:
        raise_err("ERR_UNAUTHORIZED", "role is not permitted for this endpoint")


def actor_member(role, uid):
    """Resolve the acting Member for entity-backed roles (existence stage)."""
    if role not in ENTITY_ROLES:
        return None
    member = db.store.members.get(uid)
    if member is None:
        raise_err("ERR_MEMBER_NOT_FOUND", "no member with the given X-User-ID")
    return member


def is_approved_member(member_id, group_id):
    for ms in db.store.memberships.values():
        if (ms["member_id"] == member_id and ms["group_id"] == group_id
                and ms["status"] == "APPROVED"):
            return True
    return False


def is_moderator(member_id, group_id):
    for ms in db.store.memberships.values():
        if (ms["member_id"] == member_id and ms["group_id"] == group_id
                and ms["status"] == "APPROVED" and ms["role"] == "MODERATOR"):
            return True
    return False


def require_group_moderator(role, uid, group_id):
    """PlatformAdmin always passes; GroupModerator must moderate the group."""
    if role == "PlatformAdmin":
        return
    if role == "GroupModerator" and is_moderator(uid, group_id):
        return
    raise_err("ERR_UNAUTHORIZED", "actor does not moderate the target group")


def require_active(member):
    if member["status"] == "SUSPENDED":
        raise_err("ERR_MEMBER_SUSPENDED", "member is suspended")
    if member["status"] == "BANNED":
        raise_err("ERR_MEMBER_BANNED", "member is banned")


# ---------------------------------------------------------------------------
# Body field validators
# ---------------------------------------------------------------------------

def validate(body, spec):
    """spec: {field: (required: bool, validator: fn) }.
    Unknown fields are rejected. Returns {field: value} with MISSING for
    absent optional fields. Validators raise ERR_VALIDATION on bad input."""
    for key in body:
        if key not in spec:
            raise_err("ERR_VALIDATION", f"unknown field: {key}")
    out = {}
    for name, (required, fn) in spec.items():
        if name not in body:
            if required:
                raise_err("ERR_VALIDATION", f"missing required field: {name}")
            out[name] = MISSING
            continue
        value = body[name]
        if value is None:
            out[name] = fn(value)  # validator decides whether null is legal
            continue
        out[name] = fn(value)
    return out


def v_str(v):
    if not isinstance(v, str) or v == "":
        raise_err("ERR_VALIDATION", "expected a non-empty string")
    return v


def v_str_empty_ok(v):
    if not isinstance(v, str):
        raise_err("ERR_VALIDATION", "expected a string")
    return v


def v_email(v):
    if not isinstance(v, str) or not EMAIL_RE.match(v):
        raise_err("ERR_VALIDATION", "invalid email address")
    return v


def v_zip(v):
    if not isinstance(v, str) or not ZIP_RE.match(v):
        raise_err("ERR_VALIDATION", "zip_code must be a 5-digit string")
    return v


def v_enum(*values):
    def check(v):
        if v not in values:
            raise_err("ERR_VALIDATION", f"value must be one of {sorted(values)}")
        return v
    return check


def v_nullable_enum(*values):
    def check(v):
        if v is None:
            return None
        if v not in values:
            raise_err("ERR_VALIDATION", f"value must be one of {sorted(values)}")
        return v
    return check


def v_int(min_v=None, max_v=None):
    def check(v):
        if isinstance(v, bool) or not isinstance(v, int):
            raise_err("ERR_VALIDATION", "expected an integer")
        if min_v is not None and v < min_v:
            raise_err("ERR_VALIDATION", f"value must be >= {min_v}")
        if max_v is not None and v > max_v:
            raise_err("ERR_VALIDATION", f"value must be <= {max_v}")
        return v
    return check


def v_datetime(v):
    dt = parse_iso(v)
    if dt is None:
        raise_err("ERR_VALIDATION", "expected an ISO 8601 datetime string")
    return dt
