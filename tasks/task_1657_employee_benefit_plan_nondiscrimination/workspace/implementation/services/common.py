"""Shared helpers: serialization, validation, pagination, lookups."""

import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import request

from db import store
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND

Q4 = Decimal("0.0001")


def new_id():
    return str(uuid.uuid4())


def now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def touch(obj):
    obj["updated_at"] = now_iso()


def bump(obj):
    obj["version"] = int(obj.get("version", 0)) + 1
    touch(obj)


def new_entity(extra):
    ts = now_iso()
    base = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}
    base.update(extra)
    return base


# --------------------------------------------------------------------------
# JSON body + field validation
# --------------------------------------------------------------------------

def get_body():
    if not request.is_json:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be JSON")
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return body


def _bad(message):
    return ApiError(ERR_INVALID_REQUEST, 400, message)


def req_string(body, name):
    if name not in body:
        raise _bad("Missing required field: %s" % name)
    value = body[name]
    if not isinstance(value, str) or value == "":
        raise _bad("Field %s must be a non-empty string" % name)
    return value


def opt_string(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str) or value == "":
        raise _bad("Field %s must be a non-empty string" % name)
    return value


def req_enum(body, name, members):
    value = req_string(body, name)
    if value not in members:
        raise _bad("Field %s must be one of %s" % (name, sorted(members)))
    return value


def opt_enum(body, name, members, default=None):
    if name not in body or body[name] is None:
        return default
    return req_enum(body, name, members)


def req_int(body, name):
    if name not in body:
        raise _bad("Missing required field: %s" % name)
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad("Field %s must be an integer" % name)
    return value


def opt_int(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return req_int(body, name)


def req_bool(body, name):
    if name not in body:
        raise _bad("Missing required field: %s" % name)
    value = body[name]
    if not isinstance(value, bool):
        raise _bad("Field %s must be a boolean" % name)
    return value


def opt_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return req_bool(body, name)


def req_number(body, name):
    """Numeric percentage; accepts int/float, rejects bool and non-numbers."""
    if name not in body:
        raise _bad("Missing required field: %s" % name)
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _bad("Field %s must be a number" % name)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise _bad("Field %s must be a number" % name)
    return dec


def opt_number(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return req_number(body, name)


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


def parse_date(value, field):
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise _bad("Field %s must be an ISO date (YYYY-MM-DD)" % field)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _bad("Field %s is not a valid calendar date" % field)


def req_date(body, name):
    if name not in body:
        raise _bad("Missing required field: %s" % name)
    return parse_date(body[name], name)


def opt_date(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return parse_date(body[name], name)


def parse_datetime(value, field):
    if not isinstance(value, str) or not DATETIME_RE.match(value):
        raise _bad("Field %s must be an ISO 8601 datetime" % field)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise _bad("Field %s is not a valid datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_date(d):
    return d.isoformat()


def to_float(dec):
    return float(dec)


# --------------------------------------------------------------------------
# Pagination (PRD §2.3: limit default 10, min 1, max 100; offset default 0)
# --------------------------------------------------------------------------

def pagination_params():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise _bad("limit must be an integer")
        if limit < 1 or limit > 100:
            raise _bad("limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise _bad("offset must be an integer")
        if offset < 0:
            raise _bad("offset must be >= 0")
    return limit, offset


def page_slice(items, limit, offset):
    ordered = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    return ordered[offset:offset + limit], len(ordered)


def opt_filter(args, name):
    value = args.get(name)
    if value is None:
        return None
    return value


# --------------------------------------------------------------------------
# Entity lookups (existence: 404 when missing)
# --------------------------------------------------------------------------

def get_employer(eid):
    e = store.employers.get(eid)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Employer not found")
    return e


def get_plan(pid):
    p = store.plans.get(pid)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Plan not found")
    return p


def get_plan_version(vid):
    v = store.plan_versions.get(vid)
    if v is None:
        raise ApiError(ERR_NOT_FOUND, 404, "PlanVersion not found")
    return v


def get_plan_year(pyid):
    py = store.plan_years.get(pyid)
    if py is None:
        raise ApiError(ERR_NOT_FOUND, 404, "PlanYear not found")
    return py


def get_employee(eid):
    e = store.census_employees.get(eid)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "CensusEmployee not found")
    return e


def get_contribution(cid):
    c = store.contributions.get(cid)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Contribution not found")
    return c


def get_test_run(tid):
    t = store.test_runs.get(tid)
    if t is None:
        raise ApiError(ERR_NOT_FOUND, 404, "TestRun not found")
    return t


def get_correction(cid):
    c = store.corrections.get(cid)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Correction not found")
    return c


def get_election(eid):
    e = store.safe_harbor_elections.get(eid)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "SafeHarborElection not found")
    return e


def get_notice(nid):
    n = store.safe_harbor_notices.get(nid)
    if n is None:
        raise ApiError(ERR_NOT_FOUND, 404, "SafeHarborNotice not found")
    return n


# --------------------------------------------------------------------------
# Aggregate traversal helpers
# --------------------------------------------------------------------------

def plan_of_year(py):
    return store.plans.get(py["plan_id"])


def employer_of_plan(plan):
    return store.employers.get(plan["employer_id"]) if plan else None


def plan_year_of_employee(emp):
    return store.plan_years.get(emp["plan_year_id"])


def plan_year_of_contribution(contrib):
    emp = store.census_employees.get(contrib["census_employee_id"])
    return plan_year_of_employee(emp) if emp else None


def active_limit_for_year(year_label):
    for lim in store.regulatory_limits.values():
        if lim["year_label"] == year_label and lim["status"] == "ACTIVE":
            return lim
    return None


def adopted_version_covering(plan_id, day):
    """Latest-created ADOPTED version whose [start, end) covers `day`."""
    covering = []
    for v in store.plan_versions.values():
        if v["plan_id"] != plan_id or v["status"] != "ADOPTED":
            continue
        start = date.fromisoformat(v["effective_start"])
        end = date.fromisoformat(v["effective_end"]) if v["effective_end"] else None
        if start <= day and (end is None or day < end):
            covering.append(v)
    if not covering:
        return None
    covering.sort(key=lambda v: (v["created_at"], v["id"]))
    return covering[-1]


def adopted_comp_definition(py):
    """Comp definition of the version covering year_start (or the pinned one)."""
    if py.get("adopted_version_id"):
        v = store.plan_versions.get(py["adopted_version_id"])
        if v is not None:
            return v["comp_definition"]
    plan = plan_of_year(py)
    if plan is None:
        return None
    v = adopted_version_covering(plan["id"], date.fromisoformat(py["year_start"]))
    return v["comp_definition"] if v else None


def comp_sum(emp_id, comp_source, period):
    total = 0
    for rec in store.compensation_records.values():
        if (rec["census_employee_id"] == emp_id
                and rec["comp_source"] == comp_source
                and rec["period"] == period):
            total += rec["amount_cents"]
    return total


def contribution_sum(emp_id, types, statuses):
    total = 0
    for c in store.contributions.values():
        if (c["census_employee_id"] == emp_id
                and c["contribution_type"] in types
                and c["status"] in statuses):
            total += c["amount_cents"]
    return total


def employees_of_year(py_id):
    return [e for e in store.census_employees.values() if e["plan_year_id"] == py_id]


def supersede_terminal_test_runs(py_id, later_than_created_at=None):
    """Mark PASSED/FAILED runs of the plan year SUPERSEDED (staleness cascade).

    When later_than_created_at is given, only runs created strictly after that
    timestamp are superseded ("every later TestRun").
    """
    for run in store.test_runs.values():
        if run["plan_year_id"] != py_id:
            continue
        if run["status"] not in ("PASSED", "FAILED"):
            continue
        if later_than_created_at is not None and run["created_at"] <= later_than_created_at:
            continue
        run["status"] = "SUPERSEDED"
        bump(run)
