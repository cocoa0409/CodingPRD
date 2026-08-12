"""Shared helpers: request-body validation, serializers, pagination,
version/timestamp bumps (PRD §2.3, §2.4)."""
import re
import uuid
from datetime import date, datetime, timezone

from flask import request

from db import DB
from errors import ApiError, invalid, not_found
from response import success
from clock import CLOCK

_DT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_id():
    return str(uuid.uuid4())


def parse_body():
    """Parse the JSON body. A missing/empty body is treated as {} so that
    bodiless POST transition endpoints work; malformed JSON -> 400."""
    data = request.get_data(cache=True)
    if data is None or data.strip() == b"":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise invalid("Request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise invalid("Request body must be a JSON object")
    return parsed


def _bool(v):
    return isinstance(v, bool)


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def _str(v):
    return isinstance(v, str)


def parse_iso_datetime(value, field):
    """Parse an ISO 8601 datetime to an aware UTC datetime. Naive inputs are
    treated as UTC. Malformed values -> ERR_INVALID_REQUEST."""
    if not isinstance(value, str):
        raise invalid(f"Field '{field}' must be an ISO 8601 datetime string")
    m = _DT_RE.match(value.strip())
    if not m:
        raise invalid(f"Field '{field}' must be an ISO 8601 datetime string")
    try:
        y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
        frac = m.group(7) or ""
        us = int((frac + "000000")[:6]) if frac else 0
        dt = datetime(y, mo, d, h, mi, s, us)
    except ValueError:
        raise invalid(f"Field '{field}' is not a valid datetime")
    tz = m.group(8)
    if tz in (None, "Z"):
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        sign = 1 if tz[0] == "+" else -1
        digits = tz[1:].replace(":", "")
        off_h, off_m = int(digits[:2]), int(digits[2:4])
        from datetime import timedelta

        offset = sign * timedelta(hours=off_h, minutes=off_m)
        dt = dt.replace(tzinfo=timezone.utc).replace(tzinfo=None)
        dt = dt - offset
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_iso_date(value, field):
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        raise invalid(f"Field '{field}' must be an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise invalid(f"Field '{field}' is not a valid date")


def require_fields(body, specs):
    """Validate required/optional fields against a spec list of
    (name, kind, required, extra). kind in {'string','int','number','bool',
    'datetime','date','enum','answers'}. Returns a dict of parsed values
    (datetimes/dates converted)."""
    out = {}
    for spec in specs:
        name, kind, required = spec[0], spec[1], spec[2]
        extra = spec[3] if len(spec) > 3 else None
        present = name in body and body[name] is not None
        if not present:
            if required:
                raise invalid(f"Missing required field: {name}")
            continue
        v = body[name]
        if kind == "string":
            if not _str(v):
                raise invalid(f"Field '{name}' must be a string")
            out[name] = v
        elif kind == "int":
            if not _int(v):
                raise invalid(f"Field '{name}' must be an integer")
            out[name] = v
        elif kind == "number":
            if not _num(v):
                raise invalid(f"Field '{name}' must be a number")
            out[name] = v
        elif kind == "bool":
            if not _bool(v):
                raise invalid(f"Field '{name}' must be a boolean")
            out[name] = v
        elif kind == "datetime":
            out[name] = parse_iso_datetime(v, name)
        elif kind == "date":
            out[name] = parse_iso_date(v, name)
        elif kind == "enum":
            if not _str(v) or v not in extra:
                raise invalid(
                    f"Field '{name}' must be one of {sorted(extra)}"
                )
            out[name] = v
        elif kind == "answers":
            if (
                not isinstance(v, list)
                or len(v) != 10
                or any(not _int(a) or a < 0 or a > 10 for a in v)
            ):
                raise invalid(
                    "Field 'answers' must be exactly 10 integers each in 0..10"
                )
            out[name] = v
        else:
            raise AssertionError(kind)
    return out


def touch(record):
    """PRD §2.4: any mutation refreshes updated_at and increments version."""
    record["updated_at"] = CLOCK.stamp_iso()
    record["version"] = record.get("version", 1) + 1


def stamp_new(record, common=True):
    """Assign id/created_at (+updated_at/version when common_fields)."""
    record["id"] = new_id()
    record["created_at"] = CLOCK.stamp_iso()
    if common:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


# --- lookup helpers (existence stage, left-to-right path validation) ---

def get_employer_or_404(eid):
    e = DB.employers.get(eid)
    if e is None:
        raise not_found("Employer")
    return e


def get_employee_or_404(eid):
    e = DB.employees.get(eid)
    if e is None:
        raise not_found("Employee")
    return e


def get_program_or_404(pid):
    p = DB.programs.get(pid)
    if p is None:
        raise not_found("WellnessProgram")
    return p


def get_enrollment_or_404(eid):
    e = DB.enrollments.get(eid)
    if e is None:
        raise not_found("Enrollment")
    return e


def get_challenge_or_404(cid):
    c = DB.challenges.get(cid)
    if c is None:
        raise not_found("Challenge")
    return c


def get_event_or_404(eid):
    e = DB.events.get(eid)
    if e is None:
        raise not_found("ActivityEvent")
    return e


def get_award_or_404(aid):
    a = DB.awards.get(aid)
    if a is None:
        raise not_found("IncentiveAward")
    return a


def get_referral_or_404(rid):
    r = DB.referrals.get(rid)
    if r is None:
        raise not_found("CoachingReferral")
    return r


def get_invoice_or_404(iid):
    inv = DB.invoices.get(iid)
    if inv is None:
        raise not_found("VendorInvoice")
    return inv


def get_screening_or_404(sid):
    s = DB.screenings.get(sid)
    if s is None:
        raise not_found("BiometricScreening")
    return s


def get_report_or_404(rid):
    r = DB.reports.get(rid)
    if r is None:
        raise not_found("AggregateReport")
    return r


# --- pagination & list responses (PRD §2.3) ---

def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise invalid("Query parameter 'limit' must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid("Query parameter 'offset' must be an integer")
        if offset < 0:
            raise invalid("Query parameter 'offset' must be >= 0")
    return limit, offset


def list_response(items, serialize, status=200):
    """Sort by created_at ascending, apply limit/offset, emit envelope."""
    items = sorted(items, key=lambda r: r["created_at"])
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset : offset + limit]
    has_more = (offset + limit) < total
    return success(
        [serialize(r) for r in page],
        response_type="array",
        status=status,
        pagination={
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": has_more,
        },
    )


# --- employee ownership helper (PRD §2.6 stage 5) ---

def check_employee_scope(enrollment):
    """For Employee callers: X-User-ID must equal enrollment.employee_id.
    Other roles pass."""
    from middleware import current_identity

    user_id, role = current_identity()
    if role == "Employee" and enrollment["employee_id"] != user_id:
        raise ApiError(
            "ERR_OWNERSHIP_MISMATCH",
            "Employee may only act on resources of their own enrollment",
        )
