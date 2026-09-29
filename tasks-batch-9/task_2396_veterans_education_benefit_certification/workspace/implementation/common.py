"""Shared plumbing: auth ladder rungs, row helpers, date helpers, pagination."""

import re
import uuid
from datetime import date, datetime, timedelta, timezone

from flask import request

from db import db
from errors import fail
from response import now_iso

# --- roles (PRD §2.1) -------------------------------------------------------
ROLE_SCO = "SchoolCertifyingOfficial"
ROLE_SUPERVISORY = "SupervisorySCO"
ROLE_BURSAR = "BursarOfficer"
ROLE_SAA = "StateApprovingAgent"
ROLE_VA = "VaProcessingOffice"
ROLE_STUDENT = "Student"

ALL_ROLES = (ROLE_SCO, ROLE_SUPERVISORY, ROLE_BURSAR, ROLE_SAA, ROLE_VA, ROLE_STUDENT)
OFFICIAL_ROLES = (ROLE_SCO, ROLE_SUPERVISORY)


class Actor(object):
    __slots__ = ("role", "user_id")

    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id


# --- ladder rungs 1 & 2 -----------------------------------------------------
def authenticate(allowed_roles):
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")
    return Actor(role, user_id)


# --- ladder rungs 4, 5 & 6 --------------------------------------------------
def require_official(actor):
    """Entity-backed official gates. Only meaningful for the two official roles."""
    if actor.role not in OFFICIAL_ROLES:
        return None
    official = db.officials.get(actor.user_id)
    if official is None:
        fail("ERR_OFFICIAL_NOT_REGISTERED")
    if official["status"] != "ACTIVE":
        fail("ERR_OFFICIAL_INACTIVE")
    expected_level = "SUPERVISORY" if actor.role == ROLE_SUPERVISORY else "SCO"
    if official["official_level"] != expected_level:
        fail("ERR_OFFICIAL_LEVEL_MISMATCH")
    return official


# --- row helpers ------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def new_row(common_fields=True):
    stamp = now_iso()
    row = {"id": new_id(), "created_at": stamp}
    if common_fields:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = db.next_seq()
    row["_dates"] = {}
    return row


def touch(row):
    """PRD §2.5: refresh updated_at and increment version on any mutation."""
    row["updated_at"] = now_iso()
    row["version"] = row["version"] + 1


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# --- date helpers -----------------------------------------------------------
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_instant(value):
    """Parse an ISO 8601 instant / date. Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if _DATE_ONLY.match(text):
            return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        normalized = text
        if normalized.endswith("Z") or normalized.endswith("z"):
            normalized = normalized[:-1] + "+00:00"
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def parse_day(value):
    """Parse a calendar date input. Returns a `date` or None when unparseable."""
    instant = parse_instant(value)
    return instant.date() if instant is not None else None


def fmt_day(day):
    """Canonical wire shape for a computed calendar date (PRD §2.6).

    Calendar dates are whole-day values, and every client-supplied calendar
    date is echoed back exactly as given (`YYYY-MM-DD`). A computed calendar
    date belongs to the same field family, so it uses the same shape rather
    than a second, instant-looking one.
    """
    if day is None:
        return None
    return day.strftime("%Y-%m-%d")


def set_input_day(row, name, raw):
    """Store a client-supplied calendar date: echo the raw string, keep the date."""
    row[name] = raw
    row["_dates"][name] = parse_day(raw) if raw is not None else None


def set_computed_day(row, name, day):
    row[name] = fmt_day(day)
    row["_dates"][name] = day


def day_of(row, name):
    return row["_dates"].get(name)


def clock_now():
    return db.clock


def clock_day():
    return db.clock.date()


def days_between(a, b):
    """Whole calendar days from a to b (b - a)."""
    return (b - a).days


def plus_days(day, count):
    return day + timedelta(days=count)


# --- pagination (PRD §2.3) --------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = DEFAULT_LIMIT
    offset = 0

    if limit_raw is not None:
        try:
            limit = int(str(limit_raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")

    if offset_raw is not None:
        try:
            offset = int(str(offset_raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must not be negative.")

    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def enum_filter(name, members):
    """Read a query filter whose domain is an enum (PRD §2.4)."""
    value = request.args.get(name)
    if value is None:
        return None
    if value not in members:
        fail("ERR_INVALID_REQUEST", "%s is not a valid value for %s." % (value, name))
    return value


def str_filter(name):
    return request.args.get(name)


def read_filters(spec):
    """spec is a sequence of (field_name, enum_members_or_None) pairs."""
    active = []
    for name, members in spec:
        value = enum_filter(name, members) if members else str_filter(name)
        if value is not None:
            active.append((name, value))
    return active


class ListQuery(object):
    """Ladder rung 3 for a collection read: pagination plus the filter vocabulary."""

    __slots__ = ("limit", "offset", "filters")

    def __init__(self, spec):
        self.limit, self.offset = pagination()
        self.filters = read_filters(spec)

    def get(self, name):
        for field, value in self.filters:
            if field == name:
                return value
        return None

    def emit(self, rows, extra=None, order_key=None):
        from response import list_response  # local import: avoids an import cycle

        selected = [r for r in rows if all(r.get(n) == v for n, v in self.filters)]
        if extra is not None:
            selected = [r for r in selected if extra(r)]
        if order_key is None:
            selected = by_created(selected)
        else:
            selected = sorted(selected, key=order_key)
        page, total = paginate(selected, self.limit, self.offset)
        return list_response([serialize(r) for r in page], self.limit, self.offset, total)


# --- path id resolution (ladder rung 7) ------------------------------------
def _lookup(collection, key, error_id):
    row = collection.get(key)
    if row is None:
        fail(error_id)
    return row


def get_official(official_id):
    return _lookup(db.officials, official_id, "ERR_OFFICIAL_NOT_FOUND")


def get_student(student_id):
    return _lookup(db.students, student_id, "ERR_STUDENT_NOT_FOUND")


def get_term(term_id):
    return _lookup(db.terms, term_id, "ERR_TERM_NOT_FOUND")


def get_program(program_id):
    return _lookup(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")


def get_catalog_version(cv_id):
    return _lookup(db.catalog_versions, cv_id, "ERR_CATALOG_VERSION_NOT_FOUND")


def get_agreement(agreement_id):
    return _lookup(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")


def get_certification(cert_id):
    return _lookup(db.certifications, cert_id, "ERR_CERTIFICATION_NOT_FOUND")


def get_tuition_report(report_id):
    return _lookup(db.tuition_reports, report_id, "ERR_TUITION_REPORT_NOT_FOUND")


def get_award(award_id):
    return _lookup(db.awards, award_id, "ERR_AWARD_NOT_FOUND")


def get_change_report(report_id):
    return _lookup(db.change_reports, report_id, "ERR_CHANGE_REPORT_NOT_FOUND")


def get_debt(debt_id):
    return _lookup(db.debts, debt_id, "ERR_DEBT_NOT_FOUND")


def get_charge(charge_id):
    return _lookup(db.charges, charge_id, "ERR_CHARGE_NOT_FOUND")


# --- audit trail (PRD §2.5) -----------------------------------------------
def append_audit(certification_id, event_type, actor_role, actor_user_id, detail):
    existing = [e for e in db.audit_entries.values() if e["certification_id"] == certification_id]
    row = new_row(common_fields=False)
    row["certification_id"] = certification_id
    row["event_type"] = event_type
    row["actor_role"] = actor_role
    row["actor_user_id"] = actor_user_id
    row["detail"] = detail
    row["sequence_index"] = len(existing) + 1
    db.audit_entries[row["id"]] = row
    return row
