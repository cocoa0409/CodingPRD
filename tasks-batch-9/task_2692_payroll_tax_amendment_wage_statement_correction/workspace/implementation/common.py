"""Foundation layer: errors, response envelope, in-memory store, logical clock,
numeric helpers, request validation and RBAC / ownership guards.

Every structural name in this module is taken from SCAFFOLD.yaml
(response_envelope, entities, validations, errors, roles) and PRD.md section 2.
"""

import os
import re
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

from flask import request, jsonify

# ---------------------------------------------------------------------------
# Error catalogue (SCAFFOLD.yaml -> errors)
# ---------------------------------------------------------------------------

ERROR_STATUS = {
    # auth / identity
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_IDENTITY_NOT_RESOLVABLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES_VIOLATION": 403,
    # existence
    "ERR_EMPLOYER_NOT_FOUND": 404,
    "ERR_TAX_AGENCY_NOT_FOUND": 404,
    "ERR_AGENCY_ACCOUNT_NOT_FOUND": 404,
    "ERR_EMPLOYEE_NOT_FOUND": 404,
    "ERR_REGISTER_LINE_NOT_FOUND": 404,
    "ERR_DEPOSIT_RECORD_NOT_FOUND": 404,
    "ERR_FILED_RETURN_NOT_FOUND": 404,
    "ERR_CORRECTION_CASE_NOT_FOUND": 404,
    "ERR_DISCREPANCY_NOT_FOUND": 404,
    "ERR_AMENDED_RETURN_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_WAGE_REPAYMENT_NOT_FOUND": 404,
    "ERR_AGENCY_NOTICE_NOT_FOUND": 404,
    "ERR_CONTROL_REMEDIATION_NOT_FOUND": 404,
    # schema
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_RECOVERY_YEAR": 400,
    # optimistic concurrency
    "ERR_STALE_CASE_VERSION": 412,
    "ERR_STALE_STATEMENT_VERSION": 412,
    # state
    "ERR_INVALID_STATE": 409,
    "ERR_AMENDED_RETURN_NOT_SIGNED": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_UNCATEGORIZED_DISCREPANCIES": 409,
    # business referential
    "ERR_SCOPE_MISMATCH": 422,
    "ERR_AGENCY_ACCOUNT_NOT_ACTIVE": 422,
    "ERR_REMEDIATION_NOT_VERIFIED": 409,
    "ERR_CASE_HAS_NO_DISCREPANCIES": 409,
    "ERR_REPAYMENT_NOT_SETTLED": 409,
    # temporal
    "ERR_AMENDMENT_WINDOW_CLOSED": 422,
    "ERR_AMENDMENT_COOLING_OFF_ACTIVE": 409,
    "ERR_INVALID_ACCRUAL_DATE": 422,
    "ERR_NOTICE_RESPONSE_OVERDUE": 422,
    "ERR_PRIOR_YEAR_WINDOW_CLOSED": 422,
    # business constraints
    "ERR_AMENDMENT_SLOT_OCCUPIED": 409,
    "ERR_ACCOUNT_PERIOD_OVERLAP": 409,
    "ERR_DUPLICATE_FILED_RETURN": 409,
    "ERR_DUPLICATE_EMPLOYER_FEIN": 409,
    "ERR_DUPLICATE_NOTICE_NUMBER": 409,
    "ERR_DUPLICATE_AGENCY_CODE": 409,
    "ERR_NO_REPORTABLE_DELTA": 422,
    "ERR_NO_FILED_RETURN_FOR_PERIOD": 422,
    "ERR_CHANNEL_NOT_UNDELIVERABLE_CAPABLE": 422,
    # fiscal
    "ERR_AUTHORIZATION_LIMIT_EXCEEDED": 422,
    "ERR_OVERCOLLECTION": 422,
    "ERR_WAIVER_EXCEEDS_ASSESSMENT": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------

_ID_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ID_ALPHABET) for _ in range(20))


def iso(dt):
    """ISO-8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5) + in-memory store (PRD 2.4)
# ---------------------------------------------------------------------------

INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

OPEN_ENDED_ORDINAL = 999999


class Store:
    """In-memory storage.  Starts completely empty on every boot."""

    def __init__(self):
        self.now = INITIAL_CLOCK
        self.employers = {}
        self.tax_agencies = {}
        self.agency_accounts = {}
        self.employees = {}
        self.register_lines = {}
        self.deposit_records = {}
        self.filed_returns = {}
        self.correction_cases = {}
        self.discrepancies = {}
        self.amended_returns = {}
        self.statements = {}
        self.wage_repayments = {}
        self.agency_notices = {}
        self.control_remediations = {}
        self._seq = 0

    def seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return db.now


def new_row(extra=None, versioned=True):
    row = {"id": new_id(), "created_at": db.now, "_seq": db.seq()}
    if versioned:
        row["updated_at"] = db.now
        row["version"] = 1
    if extra:
        row.update(extra)
    return row


def touch(row):
    row["updated_at"] = db.now
    row["version"] = row.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Numeric helpers (PRD 2.6) -- exact integer arithmetic, ROUND_HALF_UP
# ---------------------------------------------------------------------------

def rhu(numerator, denominator):
    """ROUND_HALF_UP of numerator/denominator to a whole unit.

    Ties are rounded away from zero, matching decimal.ROUND_HALF_UP.
    Exact integer arithmetic -- no binary floating point anywhere.
    """
    if denominator == 0:
        return 0
    neg = (numerator < 0) != (denominator < 0)
    n = abs(numerator)
    d = abs(denominator)
    q, r = divmod(n, d)
    if 2 * r >= d:
        q += 1
    return -q if neg else q


def whole_days(start, end):
    """Whole elapsed 24-hour spans between two instants; remainder discarded."""
    if start is None or end is None:
        return 0
    return int((end - start).total_seconds() // 86400)


def period_ordinal(tax_year, quarter):
    return tax_year * 4 + (quarter - 1)


_DUE_MONTH_DAY = {1: (4, 30), 2: (7, 31), 3: (10, 31), 4: (1, 31)}


def statutory_due_date(tax_year, quarter):
    month, day = _DUE_MONTH_DAY[quarter]
    year = tax_year + 1 if quarter == 4 else tax_year
    return datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)


def parse_datetime(value):
    """Parse an ISO-8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Request body validation (PRD 2.8 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

FEIN_RE = re.compile(r"^[0-9]{2}-[0-9]{7}$")
AGENCY_CODE_RE = re.compile(r"^[A-Z0-9-]{3,16}$")
LAST4_RE = re.compile(r"^[0-9]{4}$")
STATE_RE = re.compile(r"^[A-Z]{2}$")
JURISDICTION_RE = re.compile(r"^[A-Z0-9]{2,8}$")


def get_body():
    """Return the parsed JSON object body, or {} when no body was sent."""
    raw = request.get_data()
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(silent=True, force=True)
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return parsed


def _bad(name, why):
    fail("ERR_INVALID_REQUEST", "field '%s' %s" % (name, why))


def _check_one(name, value, spec):
    kind = spec["type"]
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad(name, "must be an integer")
        if "minimum" in spec and value < spec["minimum"]:
            _bad(name, "must be >= %d" % spec["minimum"])
        if "maximum" in spec and value > spec["maximum"]:
            _bad(name, "must be <= %d" % spec["maximum"])
        if spec.get("exclusive_minimum") is not None and value <= spec["exclusive_minimum"]:
            _bad(name, "must be > %d" % spec["exclusive_minimum"])
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            _bad(name, "must be a boolean")
        return value
    if kind == "string":
        if not isinstance(value, str):
            _bad(name, "must be a string")
        if "min_len" in spec and len(value) < spec["min_len"]:
            _bad(name, "is too short")
        if "max_len" in spec and len(value) > spec["max_len"]:
            _bad(name, "is too long")
        if "pattern" in spec and not spec["pattern"].match(value):
            _bad(name, "has an invalid format")
        if "enum" in spec and value not in spec["enum"]:
            _bad(name, "must be one of %s" % ", ".join(spec["enum"]))
        return value
    if kind == "datetime":
        if not isinstance(value, str):
            _bad(name, "must be an ISO-8601 timestamp string")
        parsed = parse_datetime(value)
        if parsed is None:
            _bad(name, "must be an ISO-8601 timestamp string")
        return parsed
    raise AssertionError("unknown field kind " + kind)


def validate(body, spec):
    """Validate a request body against a field specification.

    ``spec`` maps field name -> dict with at least ``type`` and ``required``.
    Unknown fields present in the body are ignored (PRD 2.8).
    Returns a dict of the coerced values that were actually supplied.
    """
    out = {}
    for name, rules in spec.items():
        if name not in body or body[name] is None:
            if rules.get("required"):
                if name not in body:
                    _bad(name, "is required")
                _bad(name, "may not be null")
            continue
        out[name] = _check_one(name, body[name], rules)
    return out


# Reusable field specs ------------------------------------------------------

def F(kind, required=False, **kw):
    d = {"type": kind, "required": required}
    d.update(kw)
    return d


def cents(required=False):
    return F("integer", required, minimum=0)


def tax_year_field(required=False):
    return F("integer", required, minimum=2000, maximum=2100)


def quarter_field(required=False):
    return F("integer", required, minimum=1, maximum=4)


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer")
        if str(raw).strip() != str(limit):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer")
        if str(raw).strip() != str(offset):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be >= 0")
    return limit, offset


def qs_int(name):
    """Read an integer query filter; a non-integer value simply matches nothing."""
    if name not in request.args:
        return None
    raw = request.args.get(name)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return "__nomatch__"


def qs_bool(name):
    if name not in request.args:
        return None
    raw = (request.args.get(name) or "").strip().lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    return "__nomatch__"


def qs(name):
    if name not in request.args:
        return None
    return request.args.get(name)


def sorted_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)


def matches(row, filters):
    for field, wanted in filters.items():
        if wanted is None:
            continue
        if row.get(field) != wanted:
            return False
    return True


# ---------------------------------------------------------------------------
# Authentication / RBAC / ownership (PRD 2.1, 2.10 steps 1-4)
# ---------------------------------------------------------------------------

R_ADMIN = "PlatformAdmin"
R_ANALYST = "PayrollAnalyst"
R_PREPARER = "TaxPreparer"
R_OFFICER = "TaxOfficer"
R_AUDITOR = "ControlsAuditor"
R_EMPLOYER = "EmployerRep"
R_EMPLOYEE = "EmployeeSelfService"

ALL_ROLES = (R_ADMIN, R_ANALYST, R_PREPARER, R_OFFICER, R_AUDITOR, R_EMPLOYER, R_EMPLOYEE)

# The standard six-role read set (everything except EmployeeSelfService).
READ6 = (R_ADMIN, R_ANALYST, R_PREPARER, R_OFFICER, R_AUDITOR, R_EMPLOYER)
# Reads open to all seven roles.
READ7 = ALL_ROLES


class Actor:
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    # -- ownership scope ---------------------------------------------------
    def require_employer(self, employer_id):
        if self.role == R_EMPLOYER and employer_id != self.user_id:
            fail("ERR_NOT_RESOURCE_OWNER", "resource lies outside the caller's employer scope")

    def require_employee(self, employee_id):
        if self.role == R_EMPLOYEE and employee_id != self.user_id:
            fail("ERR_NOT_RESOURCE_OWNER", "resource lies outside the caller's employee scope")

    def scoped_employer(self, requested):
        """Employer filter for list endpoints: force the caller's own scope."""
        if self.role == R_EMPLOYER:
            if requested is not None and requested != self.user_id:
                fail("ERR_NOT_RESOURCE_OWNER", "cannot list another employer's chain")
            return self.user_id
        return requested

    def scoped_employee(self, requested):
        if self.role == R_EMPLOYEE:
            if requested is not None and requested != self.user_id:
                fail("ERR_NOT_RESOURCE_OWNER", "cannot list another employee's rows")
            return self.user_id
        return requested


def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or uid.strip() == "" or role is None or role.strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required")
    uid = uid.strip()
    role = role.strip()
    if role not in ALL_ROLES:
        fail("ERR_FORBIDDEN_ROLE", "unknown role")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "role %s may not perform this operation" % role)
    if role == R_EMPLOYER and uid not in db.employers:
        fail("ERR_IDENTITY_NOT_RESOLVABLE", "X-User-ID does not resolve to an employer")
    if role == R_EMPLOYEE and uid not in db.employees:
        fail("ERR_IDENTITY_NOT_RESOLVABLE", "X-User-ID does not resolve to an employee")
    return Actor(uid, role)


# ---------------------------------------------------------------------------
# Existence lookups (PRD 2.10 steps 5-6)
# ---------------------------------------------------------------------------

def _lookup(table, key, err):
    if not isinstance(key, str) or key not in table:
        fail(err)
    return table[key]


def get_employer(key):
    return _lookup(db.employers, key, "ERR_EMPLOYER_NOT_FOUND")


def get_agency(key):
    return _lookup(db.tax_agencies, key, "ERR_TAX_AGENCY_NOT_FOUND")


def get_account(key):
    return _lookup(db.agency_accounts, key, "ERR_AGENCY_ACCOUNT_NOT_FOUND")


def get_employee(key):
    return _lookup(db.employees, key, "ERR_EMPLOYEE_NOT_FOUND")


def get_register_line(key):
    return _lookup(db.register_lines, key, "ERR_REGISTER_LINE_NOT_FOUND")


def get_deposit(key):
    return _lookup(db.deposit_records, key, "ERR_DEPOSIT_RECORD_NOT_FOUND")


def get_filed_return(key):
    return _lookup(db.filed_returns, key, "ERR_FILED_RETURN_NOT_FOUND")


def get_case(key):
    return _lookup(db.correction_cases, key, "ERR_CORRECTION_CASE_NOT_FOUND")


def get_discrepancy(key):
    return _lookup(db.discrepancies, key, "ERR_DISCREPANCY_NOT_FOUND")


def get_amended_return(key):
    return _lookup(db.amended_returns, key, "ERR_AMENDED_RETURN_NOT_FOUND")


def get_statement(key):
    return _lookup(db.statements, key, "ERR_STATEMENT_NOT_FOUND")


def get_repayment(key):
    return _lookup(db.wage_repayments, key, "ERR_WAGE_REPAYMENT_NOT_FOUND")


def get_notice(key):
    return _lookup(db.agency_notices, key, "ERR_AGENCY_NOTICE_NOT_FOUND")


def get_remediation(key):
    return _lookup(db.control_remediations, key, "ERR_CONTROL_REMEDIATION_NOT_FOUND")


def fk(body, name, getter):
    """Body foreign-key existence check -- only when a usable value was sent."""
    value = body.get(name)
    if isinstance(value, str) and value != "":
        return getter(value)
    return None


# ---------------------------------------------------------------------------
# State helpers (PRD 2.10 step 12)
# ---------------------------------------------------------------------------

def require_state(current, allowed, terminal, invalid_error="ERR_INVALID_STATE"):
    """Terminal states answer ERR_ALREADY_TERMINAL; other non-permitted states
    answer ERR_INVALID_STATE (PRD 2.10)."""
    if current in allowed:
        return
    if current in terminal:
        fail("ERR_ALREADY_TERMINAL", "entity is already in terminal state %s" % current)
    fail(invalid_error, "state %s does not permit this transition" % current)
