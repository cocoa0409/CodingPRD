"""Shared request-handling helpers: auth, body validation, pagination,
common entity fields, and cross-entity resolvers."""

import uuid
from datetime import datetime, date, timezone

import db
from errors import (
    err_unauthenticated, err_unauthorized_role, err_not_resource_owner,
    err_validation, err_not_found,
)

ROLES = {"ProducerRep", "UnionRep", "FundTrustee", "Arbitrator", "PlatformAdmin"}
ALL_ROLES = ["ProducerRep", "UnionRep", "FundTrustee", "Arbitrator", "PlatformAdmin"]


# ---------------------------------------------------------------------------
# Auth (validation priorities 1-3)
# ---------------------------------------------------------------------------

def authenticate():
    """Priority 1: headers present and role is declared."""
    role = None
    user_id = None
    from flask import request
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise err_unauthenticated()
    return user_id, role


def require_role(role, allowed):
    """Priority 2: role in the endpoint's roles list."""
    if role not in allowed:
        raise err_unauthorized_role()


def check_ownership(role, user_id, company_id):
    """Priority 3: ProducerRep ownership."""
    if role == "ProducerRep" and user_id != company_id:
        raise err_not_resource_owner()


# ---------------------------------------------------------------------------
# Body validation (priority 4)
# ---------------------------------------------------------------------------

def get_json_body():
    from flask import request
    if not request.is_json:
        raise err_validation("Request body must be JSON")
    try:
        body = request.get_json()
    except Exception:
        raise err_validation("Request body is not valid JSON")
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object")
    return body


def reject_unknown_fields(body, allowed):
    for key in body:
        if key not in allowed:
            raise err_validation(f"Unknown field: {key}")


def req_string(body, field):
    if field not in body:
        raise err_validation(f"Missing required field: {field}")
    v = body[field]
    if not isinstance(v, str):
        raise err_validation(f"Field {field} must be a string")
    return v


def opt_string(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err_validation(f"Field {field} must be a string")
    return v


def req_enum(body, field, members):
    v = req_string(body, field)
    if v not in members:
        raise err_validation(f"Field {field} must be one of {sorted(members)}")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(body, field, min_v=None, max_v=None):
    if field not in body:
        raise err_validation(f"Missing required field: {field}")
    v = body[field]
    if not _is_int(v):
        raise err_validation(f"Field {field} must be an integer")
    if min_v is not None and v < min_v:
        raise err_validation(f"Field {field} below minimum {min_v}")
    if max_v is not None and v > max_v:
        raise err_validation(f"Field {field} above maximum {max_v}")
    return v


def opt_int(body, field, default=None, min_v=None, max_v=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not _is_int(v):
        raise err_validation(f"Field {field} must be an integer")
    if min_v is not None and v < min_v:
        raise err_validation(f"Field {field} below minimum {min_v}")
    if max_v is not None and v > max_v:
        raise err_validation(f"Field {field} above maximum {max_v}")
    return v


def req_date(body, field):
    v = req_string(body, field)
    return parse_date_strict(v, field)


def opt_date(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err_validation(f"Field {field} must be a string")
    return parse_date_strict(v, field)


def parse_date_strict(v, field="date"):
    try:
        if len(v) != 10 or v[4] != "-" or v[7] != "-":
            raise ValueError
        return date(int(v[0:4]), int(v[5:7]), int(v[8:10]))
    except (ValueError, IndexError):
        raise err_validation(f"Field {field} must be an ISO 8601 date (YYYY-MM-DD)")


def parse_datetime_iso(v, field="to_iso8601"):
    if not isinstance(v, str):
        raise err_validation(f"Field {field} must be an ISO 8601 datetime string")
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err_validation(f"Field {field} must be an ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Common resource fields (id / created_at / updated_at / version)
# ---------------------------------------------------------------------------

def now_stamp():
    """created_at / updated_at timestamp: ISO 8601 UTC, three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_entity():
    ts = now_stamp()
    return {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts, "version": 1}


def touch(entity):
    entity["updated_at"] = now_stamp()


def bump(entity):
    entity["version"] += 1
    touch(entity)


def clock_stamp():
    """Logical-clock timestamp (for signatory_since)."""
    dt = db.get_clock()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_date():
    return db.get_clock().date()


# ---------------------------------------------------------------------------
# Pagination (priority 4 on query params; scaffold limit/offset defaults)
# ---------------------------------------------------------------------------

def parse_pagination():
    from flask import request
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_validation("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_validation("offset must be an integer")
        if offset < 0:
            raise err_validation("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Existence resolvers (priority 5)
# ---------------------------------------------------------------------------

def _lookup(store, rid):
    ent = store.get(rid)
    if ent is None:
        raise err_not_found()
    return ent


def get_company(cid):
    return _lookup(db.companies, cid)


def get_application(aid):
    return _lookup(db.applications, aid)


def get_production(pid):
    return _lookup(db.productions, pid)


def get_bond(bid):
    return _lookup(db.bonds, bid)


def get_assignment(aid):
    return _lookup(db.crew_assignments, aid)


def get_worklog(lid):
    return _lookup(db.work_day_logs, lid)


def get_grievance(gid):
    return _lookup(db.grievances, gid)


def get_report(rid):
    return _lookup(db.contribution_reports, rid)


def get_audit(aid):
    return _lookup(db.audits, aid)


def get_fm_event(eid):
    return _lookup(db.force_majeure_events, eid)


def bond_of_production(production_id):
    for b in db.bonds.values():
        if b["production_id"] == production_id:
            return b
    return None


def owning_company_id_of_production(production):
    return production["producer_company_id"]
