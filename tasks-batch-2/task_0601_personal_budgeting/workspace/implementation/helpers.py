"""Shared request-parsing, validation, pagination helpers."""

from flask import request, g

import errors
from db import db


# ---------------------------------------------------------------------------
# Body parsing & field validation (ERR_INVALID_REQUEST = 400)
# ---------------------------------------------------------------------------

def get_body():
    if request.method in ("POST", "PATCH", "PUT"):
        if request.content_length in (None, 0) and not (request.data or b""):
            return {}
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            raise errors.invalid_request("Malformed JSON body")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise errors.invalid_request("Request body must be a JSON object")
        return data
    return {}


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.invalid_request("Missing required field: " + name)
    return body[name]


def require_str(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request("Field must be a non-empty string: " + name)
    return val


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, str):
        raise errors.invalid_request("Field must be a string: " + name)
    return val


def require_int(body, name):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field must be an integer: " + name)
    return val


def opt_int(body, name, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field must be an integer: " + name)
    return val


def require_bool(body, name):
    val = require_field(body, name)
    if not isinstance(val, bool):
        raise errors.invalid_request("Field must be a boolean: " + name)
    return val


def opt_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise errors.invalid_request("Field must be a boolean: " + name)
    return val


def require_enum(body, name, allowed):
    val = require_str(body, name)
    if val not in allowed:
        raise errors.invalid_request("Field %s must be one of %s" % (name, sorted(allowed)))
    return val


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10 min 1 max 100; offset default 0
# ---------------------------------------------------------------------------

def parse_pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def sort_by_created(items):
    # Sort by created_at then internal sequence so concurrent same-ms creations
    # keep a stable, deterministic chronological order.
    return sorted(items, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def paginate_and_respond(items, serializer):
    from response import list_success
    limit, offset = parse_pagination()
    ordered = sort_by_created(items)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return list_success([serializer(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Ownership: entity-backed roles (Owner/Member) must act within their own
# household. PlatformAdmin is opaque and bypasses ownership.
# ---------------------------------------------------------------------------

def acting_member_household_id():
    """For an entity-backed role, resolve the household_id of the acting member.
    Returns None for PlatformAdmin."""
    if g.user_role == "PlatformAdmin":
        return None
    member = db.members.get(g.user_id)
    if member is None:
        # X-User-ID does not name a member -> cannot act within any household.
        raise errors.forbidden()
    return member["household_id"]


def enforce_household_access(household_id):
    """Owner/Member may only act within their own household. PlatformAdmin: any."""
    if g.user_role == "PlatformAdmin":
        return
    own = acting_member_household_id()
    if own != household_id:
        raise errors.forbidden()
