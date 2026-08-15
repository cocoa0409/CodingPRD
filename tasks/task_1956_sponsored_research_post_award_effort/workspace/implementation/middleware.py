"""Auth (PRD 2.1), pagination (2.3), and deferred-shape validation helpers (2.7).

Validation order is fixed: auth -> role -> ownership -> existence -> OCC ->
state -> posture -> compliance -> temporal -> structural -> referential ->
fiscal -> request shape. Request-shape failures are therefore recorded in a
Shape tracker and raised LAST, after every higher-priority check has passed.
"""
from flask import request

from db import STORES
from errors import err
from util import D, parse_dt, rhu2

ROLES = {
    "SystemAdmin",
    "SponsoredProgramsOfficer",
    "GrantCoordinator",
    "GrantsAccountant",
    "SponsorOfficial",
    "PrincipalInvestigator",
    "ResearchStaff",
}
ALL_ROLES = sorted(ROLES)


def auth():
    """Priority 1: X-User-ID and X-User-Role present, well-formed, declared role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not uid.strip():
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-ID header")
    if not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing, malformed, or undeclared X-User-Role header")
    return uid, role


def require_role(role, allowed):
    """Priority 2: role permitted on this endpoint."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s is not permitted on this endpoint" % role)


def body():
    return request.get_json(silent=True) or {}


class Shape:
    """Deferred request-shape failures (priority 13 is checked last)."""

    def __init__(self):
        self.bad = False

    def raise_if_bad(self):
        if self.bad:
            raise err("ERR_INVALID_REQUEST", "Missing required field, invalid type, enum, range, or length violation")


def sh_str(b, name, sh, required=True, min_len=None):
    v = b.get(name)
    if v is None:
        if required:
            sh.bad = True
        return None
    if not isinstance(v, str) or (min_len is not None and len(v) < min_len):
        sh.bad = True
        return None
    return v


def sh_int(b, name, sh, required=True, min_v=None, max_v=None, default=None):
    v = b.get(name)
    if v is None:
        if required:
            sh.bad = True
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        sh.bad = True
        return default
    if (min_v is not None and v < min_v) or (max_v is not None and v > max_v):
        sh.bad = True
        return default
    return v


def sh_bool(b, name, sh, default=None):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        sh.bad = True
        return default
    return v


def sh_dt(b, name, sh, required=True):
    v = b.get(name)
    if v is None:
        if required:
            sh.bad = True
        return None
    try:
        return parse_dt(v)
    except Exception:
        sh.bad = True
        return None


def sh_pct(b, name, sh, lo_exclusive, hi_inclusive, required=True):
    """Two-decimal-place percentage within (lo, hi]. Returns Decimal or None."""
    v = b.get(name)
    if v is None:
        if required:
            sh.bad = True
        return None
    try:
        d = D(v)
    except Exception:
        sh.bad = True
        return None
    if d != rhu2(d):  # more than two decimal places
        sh.bad = True
        return None
    if lo_exclusive is not None and not (d > lo_exclusive):
        sh.bad = True
        return None
    if hi_inclusive is not None and not (d <= hi_inclusive):
        sh.bad = True
        return None
    return d


def page_params():
    """limit/offset: default 10/0, min 1/0, max limit 100."""
    limit, offset = 10, 0
    raw_l = request.args.get("limit")
    raw_o = request.args.get("offset")
    if raw_l is not None:
        try:
            limit = int(raw_l)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_o is not None:
        try:
            offset = int(raw_o)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def get_or_404(store, rid, error_id):
    rec = STORES[store].get(rid) if isinstance(rid, str) else None
    if rec is None:
        raise err(error_id, "%s does not exist" % error_id.replace("ERR_", "").replace("_", " ").title())
    return rec


def list_page(store, serializer, filters=None):
    """Stable created_at-ASC sort (dict insertion order breaks ties), filters, paginate."""
    limit, offset = page_params()
    recs = list(STORES[store].values())
    if filters:
        for key, val in filters.items():
            if val is None:
                continue
            recs = [r for r in recs if key(r) == val]
    recs.sort(key=lambda r: r["created_at"])  # stable; never id-based
    total = len(recs)
    page = recs[offset:offset + limit]
    return [serializer(r) for r in page], total, limit, offset
