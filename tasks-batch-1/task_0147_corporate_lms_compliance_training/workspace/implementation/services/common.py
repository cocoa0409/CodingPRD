"""Shared helpers: common-field stamping, validation primitives, pagination,
manager-scope resolution, and FK existence checks.
"""

from decimal import Decimal, ROUND_HALF_UP

import errors
from db import db, new_id


# --- common fields --------------------------------------------------------

def stamp_create(record, common_fields=True):
    """Set id + (created_at, updated_at, version) when common_fields=True.

    Append-only records (QuizAttempt, EscalationEvent) get only id + created_at.
    """
    now = db.now()
    record["id"] = new_id()
    record["created_at"] = now
    if common_fields:
        record["updated_at"] = now
        record["version"] = 1
    return record


def touch(record):
    """Mutation bump: increment version, refresh updated_at from the clock."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = db.now()


# --- numeric / decimal ----------------------------------------------------

def round2(value):
    """Round to 2 decimals, half-up, returning a float carrying 2 dp."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


# --- input validation primitives -----------------------------------------

def require_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def req_field(body, name):
    if name not in body or body[name] is None:
        raise errors.invalid_request("Missing required field: %s" % name)
    return body[name]


def opt_field(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return body[name]


def check_enum(value, allowed, field):
    if value not in allowed:
        raise errors.invalid_request("Field %s must be one of %s" % (field, sorted(allowed)))
    return value


def check_str(value, field):
    if not isinstance(value, str) or value == "":
        raise errors.invalid_request("Field %s must be a non-empty string" % field)
    return value


def check_bool(value, field):
    if not isinstance(value, bool):
        raise errors.invalid_request("Field %s must be a boolean" % field)
    return value


def check_int(value, field):
    # bool is a subclass of int — reject it explicitly
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request("Field %s must be an integer" % field)
    return value


def check_positive_int(value, field):
    check_int(value, field)
    if value <= 0:
        raise errors.invalid_request("Field %s must be a positive integer" % field)
    return value


def check_nonneg_int(value, field):
    check_int(value, field)
    if value < 0:
        raise errors.invalid_request("Field %s must be a non-negative integer" % field)
    return value


def check_score(value, field):
    """Quiz/reported score: integer 0..100 inclusive."""
    check_int(value, field)
    if value < 0 or value > 100:
        raise errors.invalid_request("Field %s must be in 0..100" % field)
    return value


def check_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.invalid_request("Field %s must be a number" % field)
    return value


# --- pagination -----------------------------------------------------------

def parse_pagination():
    from flask import request
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at asc (stable), then slice."""
    ordered = sorted(items, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# --- existence ------------------------------------------------------------

def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise errors.not_found("Resource %s not found" % rid)
    return rec


def fk_or_404(collection, rid):
    """Body-FK existence check -> ERR_NOT_FOUND when unresolved (PRD §2.6)."""
    if rid is None:
        return None
    rec = collection.get(rid)
    if rec is None:
        raise errors.not_found("Referenced resource %s not found" % rid)
    return rec


# --- manager scope --------------------------------------------------------

def report_set(manager_id):
    """All direct & indirect reports of manager_id along Employee.manager_id."""
    result = set()
    frontier = [eid for eid, e in db.employees.items() if e.get("manager_id") == manager_id]
    while frontier:
        nxt = []
        for eid in frontier:
            if eid in result:
                continue
            result.add(eid)
            for cid, c in db.employees.items():
                if c.get("manager_id") == eid and cid not in result:
                    nxt.append(cid)
        frontier = nxt
    return result


def manager_can_see_employee(principal, employee_id):
    if principal.is_admin:
        return True
    if principal.is_manager:
        return employee_id in report_set(principal.user_id)
    if principal.is_learner:
        return employee_id == principal.user_id
    return False
