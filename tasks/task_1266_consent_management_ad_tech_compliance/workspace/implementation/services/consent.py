"""Consent domain services.

Shared helpers for the visitor/consent/DNS/scan/sweep routers:
  - datetime parsing/formatting against the logical clock
  - request auth helpers (role + visitor ownership) per SCAFFOLD validations
  - pagination argument parsing
  - ACTIVE JurisdictionPolicy / PUBLISHED ConsentBannerConfig lookup
  - retention expiry math (pinned authoritative, rolling recomputed on read)
  - the effective_consent_resolution decision waterfall (PRD section 3.5)
  - granted_purpose_count ledger maintenance
"""
from datetime import datetime, timezone, timedelta

from flask import request

from db import store, now_iso, touch
from clock import get_now
from errors import ApiError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PURPOSE_CATEGORIES = {"NECESSARY", "ANALYTICS", "ADVERTISING", "SALE_SHARE"}
SCOPE_CATEGORIES = {"ANALYTICS", "ADVERTISING", "SALE_SHARE"}
VALID_ROLES = {
    "PrivacyAdmin",
    "VendorManager",
    "ComplianceAuditor",
    "Visitor",
    "Anonymous",
    "Any",
}
READ_ROLES = {"PrivacyAdmin", "VendorManager", "ComplianceAuditor", "Visitor", "Any"}

# ---------------------------------------------------------------------------
# Datetime helpers (logical clock only)
# ---------------------------------------------------------------------------


def parse_dt(value):
    """Parse an ISO8601 datetime (accepts trailing Z). Returns aware UTC
    datetime or None when unparseable/missing."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fmt_dt(dt):
    """Format an aware datetime as ISO8601 UTC with 3 fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_days(dt, days):
    return dt + timedelta(days=int(days))


# ---------------------------------------------------------------------------
# Auth helpers (SCAFFOLD validations priority 1, 2, 2.5)
# ---------------------------------------------------------------------------


def current_user_id():
    return request.headers.get("X-User-ID")


def current_role():
    return request.headers.get("X-User-Role")


def authenticate():
    uid = current_user_id()
    role = current_role()
    if not uid or role not in VALID_ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and the role must be recognized",
            400,
        )
    return uid, role


def check_role(*roles):
    """Role gate for mutating endpoints. 'Any' means any authenticated role."""
    _, role = authenticate()
    if "Any" not in roles and role not in roles:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "Role %s is not permitted for this operation" % role,
            403,
        )


def check_read_role():
    """Read gate: every authenticated role except Anonymous may read."""
    _, role = authenticate()
    if role not in READ_ROLES:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "Role %s is not permitted for this operation" % role,
            403,
        )


def check_ownership(visitor_id):
    """Visitor callers may only act on their own profile."""
    if current_role() == "Visitor" and current_user_id() != visitor_id:
        raise ApiError(
            "ERR_FORBIDDEN_OWNERSHIP",
            "Visitor role may only act on its own visitor profile",
            403,
        )


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def pagination_args():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer", 400)
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer", 400)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def sort_created(items):
    return sorted(items, key=lambda e: e.get("created_at") or "")


# ---------------------------------------------------------------------------
# Entity lookups
# ---------------------------------------------------------------------------


def get_visitor_or_404(visitor_id):
    visitor = store["visitors"].get(visitor_id)
    if visitor is None:
        raise ApiError("ERR_VISITOR_NOT_FOUND", "VisitorProfile not found", 404)
    return visitor


def active_policies(property_id, jurisdiction_code):
    pols = [
        p
        for p in store["jurisdiction_policies"].values()
        if p.get("property_id") == property_id
        and p.get("jurisdiction_code") == jurisdiction_code
        and p.get("status") == "ACTIVE"
    ]
    pols.sort(key=lambda p: p.get("created_at") or "")
    return pols


def policy_in_window(policy, now):
    """Half-open [effective_from, effective_to) coverage check."""
    ef = parse_dt(policy.get("effective_from"))
    et = parse_dt(policy.get("effective_to"))
    if ef is not None and now < ef:
        return False
    if et is not None and now >= et:
        return False
    return True


def covering_policy(property_id, jurisdiction_code, now=None):
    """The ACTIVE policy whose window contains now, else None."""
    now = now or get_now()
    for p in active_policies(property_id, jurisdiction_code):
        if policy_in_window(p, now):
            return p
    return None


def applicable_policy(visitor):
    """ACTIVE policy governing this visitor: the one covering now if any,
    else the earliest-created ACTIVE policy for the jurisdiction."""
    pols = active_policies(visitor.get("property_id"), visitor.get("jurisdiction_code"))
    if not pols:
        return None
    now = get_now()
    for p in pols:
        if policy_in_window(p, now):
            return p
    return pols[0]


def published_config(property_id, jurisdiction_code):
    cfgs = [
        c
        for c in store["banner_configs"].values()
        if c.get("property_id") == property_id
        and c.get("jurisdiction_code") == jurisdiction_code
        and c.get("status") == "PUBLISHED"
    ]
    if not cfgs:
        return None
    cfgs.sort(key=lambda c: c.get("published_at") or c.get("created_at") or "")
    return cfgs[-1]


def property_frozen(prop):
    """Defensive posture read: FROZEN field plus lazy sweep derivation."""
    if prop is None:
        return False
    if prop.get("posture") == "FROZEN":
        return True
    pid = prop.get("id")
    return any(
        s.get("property_id") == pid and s.get("status") == "ESCALATED"
        for s in store["regulatory_sweeps"].values()
    )


# ---------------------------------------------------------------------------
# Consent record helpers
# ---------------------------------------------------------------------------


def find_live_record(visitor_id, purpose_category):
    """The single GRANTED/WITHDRAWN record for (visitor, purpose), if any.
    EXPIRED records are treated as absent."""
    cands = [
        r
        for r in store["consent_records"].values()
        if r.get("visitor_id") == visitor_id
        and r.get("purpose_category") == purpose_category
        and r.get("status") in ("GRANTED", "WITHDRAWN")
    ]
    if not cands:
        return None
    cands.sort(key=lambda r: r.get("created_at") or "")
    return cands[-1]


def recompute_rolling(record):
    """expires_at_rolling = last_changed_at + live policy.retention_days.
    Recomputed on read; keeps the previous value when no ACTIVE policy."""
    visitor = store["visitors"].get(record.get("visitor_id"))
    if visitor is None:
        return
    policy = covering_policy(visitor.get("property_id"), visitor.get("jurisdiction_code"))
    if policy is None:
        pols = active_policies(visitor.get("property_id"), visitor.get("jurisdiction_code"))
        policy = pols[0] if pols else None
    if policy is None:
        return
    lc = parse_dt(record.get("last_changed_at"))
    if lc is None:
        return
    record["expires_at_rolling"] = fmt_dt(add_days(lc, policy.get("retention_days", 0)))


def recompute_expiries(record):
    """Recompute pinned (from snapshot) and rolling horizons after a
    transition into GRANTED or WITHDRAWN (last_changed_at moved)."""
    lc = parse_dt(record.get("last_changed_at"))
    snap = record.get("policy_snapshot_retention_days")
    if lc is not None and snap is not None:
        record["expires_at_pinned"] = fmt_dt(add_days(lc, snap))
    recompute_rolling(record)


def adjust_granted_count(property_id, delta):
    """granted_purpose_count ledger sync; every adjustment bumps the property."""
    prop = store["properties"].get(property_id)
    if prop is None:
        return
    new_val = int(prop.get("granted_purpose_count", 0)) + delta
    if new_val < 0:
        new_val = 0
    prop["granted_purpose_count"] = new_val
    touch(prop)


# ---------------------------------------------------------------------------
# effective_consent_resolution waterfall (PRD 3.5 / SCAFFOLD calculations)
# ---------------------------------------------------------------------------


def effective_decision(visitor, purpose_category):
    now = get_now()
    pols = active_policies(visitor.get("property_id"), visitor.get("jurisdiction_code"))
    policy = None
    for p in pols:
        if policy_in_window(p, now):
            policy = p
            break
    if policy is None and pols:
        policy = pols[0]

    # 1. CHILD may only receive NECESSARY
    if visitor.get("age_status") == "CHILD" and purpose_category != "NECESSARY":
        return "BLOCKED_CHILD"
    # 2. NECESSARY is always granted (no record stored)
    if purpose_category == "NECESSARY":
        return "ALWAYS_GRANTED"

    record = find_live_record(visitor.get("id"), purpose_category)

    # 3. SALE_SHARE under a gpc_honored policy with the signal ON
    if (
        purpose_category == "SALE_SHARE"
        and policy is not None
        and policy.get("gpc_honored")
        and visitor.get("gpc_effective") == "ON"
    ):
        gpc_at = parse_dt(visitor.get("gpc_updated_at"))
        if record is not None and record.get("status") == "GRANTED" and gpc_at is not None:
            lc = parse_dt(record.get("last_changed_at"))
            if lc is not None and lc > gpc_at:
                return "EXPLICIT_GRANT"
        return "FORCED_OPT_OUT"

    # 4. Existing record (EXPIRED treated as absent upstream)
    if record is not None:
        if record.get("status") == "GRANTED":
            return "EXPLICIT_GRANT"
        if record.get("status") == "WITHDRAWN":
            return "EXPLICIT_WITHDRAWN"

    # 5. Regime default
    regime = (policy or {}).get("banner_regime")
    if regime == "OPT_IN_REQUIRED":
        return "DENIED_BY_DEFAULT"
    if regime in ("OPT_OUT_ALLOWED", "NOTICE_ONLY"):
        return "GRANTED_BY_DEFAULT"
    return "DENIED_BY_DEFAULT"
