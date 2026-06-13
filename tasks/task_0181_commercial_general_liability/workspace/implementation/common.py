"""Shared helpers: common fields, datetime parsing/comparison, pagination, auth."""
from datetime import datetime, timezone

from flask import request

from db import db, new_id, iso_now_real
import errors
from errors import err

ROLES = {"InsurerAdmin", "Underwriter", "ClaimsAdjuster", "PremiumAuditor", "CertificateHolder"}


# ---------------------------------------------------------------------------
# Datetime parsing & comparison
# ---------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None for None. Raises ValueError on a malformed string.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("datetime must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Common resource fields (PRD §2.4)
# ---------------------------------------------------------------------------
def attach_common(record, with_version=True):
    """Attach id, created_at, updated_at, version on create.

    ClaimTransaction is the single exception (with_version=False, no updated_at):
    it is an immutable ledger entry carrying only id and created_at.
    """
    record["id"] = new_id()
    record["created_at"] = iso_now_real()
    record["_seq"] = db.next_seq()
    if with_version:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and increment version on a mutation (PRD §2.4)."""
    record["updated_at"] = iso_now_real()
    record["version"] = record.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Auth / RBAC (PRD §2.1)
# ---------------------------------------------------------------------------
def get_user_context():
    """Validate X-User-ID and X-User-Role. Raise ERR_MISSING_USER_CONTEXT if bad."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise err(errors.ERR_MISSING_USER_CONTEXT, "X-User-ID header missing or malformed")
    if not role or role not in ROLES:
        raise err(errors.ERR_MISSING_USER_CONTEXT, "X-User-Role header missing or malformed")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN_FOR_ROLE,
                  "Role %s is not permitted for this operation" % role)


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    limit = request.args.get("limit", None)
    offset = request.args.get("offset", None)
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0
    return limit, offset


def sorted_by_created(records):
    """Sort by creation order ascending (PRD §2.3), using the monotonic seq."""
    return sorted(records, key=lambda r: r.get("_seq", 0))


# ---------------------------------------------------------------------------
# Request body helper
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        body = {}
    return body
