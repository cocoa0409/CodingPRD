"""Auth header extraction, role authorization, and request helpers."""
import functools

from flask import g, request

import db
from errors import err, invalid_request, not_found

ROLES = {
    "BankAdmin",
    "LendingDataOps",
    "LoanOfficer",
    "FairLendingAnalyst",
    "FairLendingOfficer",
    "ComplianceDirector",
    "RemediationSpecialist",
}


def require_roles(*allowed):
    """Decorator: priority 1 (authentication) then priority 2 (role)."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise err(
                    "ERR_UNAUTHENTICATED",
                    "Missing or undeclared X-User-Role / X-User-ID headers",
                )
            if role not in allowed:
                raise err(
                    "ERR_UNAUTHORIZED_ROLE",
                    "Role %s is not permitted for this endpoint" % role,
                )
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def body():
    """Parse the JSON request body; missing body -> {} ; non-object -> 400."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def require_field(data, name):
    if name not in data or data[name] is None:
        raise invalid_request("Missing required field: %s" % name)
    return data[name]


def check_enum(value, allowed, field):
    if value not in allowed:
        raise invalid_request(
            "Invalid value for %s: %r (allowed: %s)" % (field, value, ", ".join(allowed))
        )
    return value


def check_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_request("Field %s must be an integer" % field)
    return value


def check_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_request("Field %s must be a number" % field)
    return value


def get_or_404(store_name, rid, what="Resource"):
    rec = db.STORES[store_name].get(rid)
    if rec is None:
        raise not_found(what)
    return rec


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def list_page(store_name, filters=None):
    """Filter -> sort by created_at ascending -> paginate.

    Returns (page_records, total_count, limit, offset).
    """
    limit, offset = pagination_params()
    records = list(db.STORES[store_name].values())
    if filters:
        for key, value in filters.items():
            if value is not None:
                records = [r for r in records if r.get(key) == value]
    records.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(records)
    return records[offset : offset + limit], total, limit, offset


def occ_check(data, field, current_version):
    """Optimistic concurrency: the expected version field is required."""
    if field not in data or data[field] is None:
        raise invalid_request("Missing required field: %s" % field)
    expected = data[field]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise invalid_request("Field %s must be an integer" % field)
    if expected != current_version:
        raise err(
            "ERR_STALE_VERSION",
            "%s (%s) does not match current version %s" % (field, expected, current_version),
        )
