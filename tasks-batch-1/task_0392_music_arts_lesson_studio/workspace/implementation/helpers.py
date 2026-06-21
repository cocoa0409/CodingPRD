"""Shared utilities: serialization, pagination, lookups, time parsing, validation."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
import errors

# Public fields per entity (the order does not matter for JSON; we exclude
# internal bookkeeping like _seq). Computed/system fields are included.
INSTRUMENTS = {"PIANO", "VIOLIN", "GUITAR", "DRUMS", "VOICE", "CELLO"}
SKILL_LEVELS = {"BEGINNER", "INTERMEDIATE", "ADVANCED"}

# ----------------------------------------------------------------------------
# Serialization
# ----------------------------------------------------------------------------

def serialize(rec):
    """Return a JSON-safe copy of a record, dropping internal fields (_*)."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ----------------------------------------------------------------------------
# Time parsing / formatting
# ----------------------------------------------------------------------------

def parse_iso_ms(value):
    """Parse an ISO 8601 UTC timestamp -> integer epoch milliseconds.

    Accepts trailing 'Z' or offset. Raises ERR_INVALID_REQUEST on bad input.
    """
    if not isinstance(value, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Timestamp must be a string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Malformed ISO 8601 timestamp")


def ms_to_iso(ms):
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(ms % 1000):03d}Z"


# ----------------------------------------------------------------------------
# Rounding (monetary, round-half-up to integer cents)
# ----------------------------------------------------------------------------

def round_half_up(value):
    """round_half_up to nearest integer. value may be int/Decimal/float-as-Decimal."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_dp(value, dp):
    q = Decimal(1).scaleb(-dp)  # e.g. dp=2 -> Decimal('0.01')
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


# ----------------------------------------------------------------------------
# Validation of request bodies
# ----------------------------------------------------------------------------

def get_json_body():
    """Return parsed JSON body or {} for empty bodies. Bad JSON -> ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Malformed JSON body")
    if not isinstance(body, dict):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
    return body


def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % n)


def require_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or not v.strip():
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % name)
    return v


def require_int(body, name, minimum=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field %s below minimum" % name)
    return v


def require_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field %s must be a boolean" % name)
    return v


def require_enum(body, name, allowed):
    v = body.get(name)
    if v not in allowed:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


# ----------------------------------------------------------------------------
# Pagination (PRD §2.3 — limit default 10 min 1 max 100; offset default 0)
# ----------------------------------------------------------------------------

def parse_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (ValueError, TypeError):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(rows):
    """Sort by creation order (created_at ASC, _seq tiebreak), then page."""
    limit, offset = parse_pagination()
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


# ----------------------------------------------------------------------------
# Lookups (existence checks; path validated left-to-right per PRD §2.6)
# ----------------------------------------------------------------------------

def get_studio(studio_id):
    s = db.studios.get(studio_id)
    if s is None:
        errors.raise_error(errors.ERR_STUDIO_NOT_FOUND, "Studio not found")
    return s


def _scoped(store, ident, err, studio_id, studio_field="studio_id"):
    rec = store.get(ident)
    if rec is None or rec.get(studio_field) != studio_id:
        errors.raise_error(err, "Resource not found")
    return rec


def get_family(studio_id, family_id):
    return _scoped(db.families, family_id, errors.ERR_FAMILY_NOT_FOUND, studio_id)


def get_student(studio_id, student_id):
    st = db.students.get(student_id)
    if st is None:
        errors.raise_error(errors.ERR_STUDENT_NOT_FOUND, "Student not found")
    fam = db.families.get(st["family_id"])
    if fam is None or fam["studio_id"] != studio_id:
        errors.raise_error(errors.ERR_STUDENT_NOT_FOUND, "Student not found")
    return st


def get_instructor(studio_id, instructor_id):
    return _scoped(db.instructors, instructor_id, errors.ERR_INSTRUCTOR_NOT_FOUND, studio_id)


def get_room(studio_id, room_id):
    return _scoped(db.rooms, room_id, errors.ERR_ROOM_NOT_FOUND, studio_id)


def get_enrollment(studio_id, enrollment_id):
    return _scoped(db.enrollments, enrollment_id, errors.ERR_ENROLLMENT_NOT_FOUND, studio_id)


def get_occurrence(studio_id, occ_id):
    occ = db.lesson_occurrences.get(occ_id)
    if occ is None:
        errors.raise_error(errors.ERR_OCCURRENCE_NOT_FOUND, "Occurrence not found")
    enr = db.enrollments.get(occ["enrollment_id"])
    if enr is None or enr["studio_id"] != studio_id:
        errors.raise_error(errors.ERR_OCCURRENCE_NOT_FOUND, "Occurrence not found")
    return occ


def get_credit(studio_id, credit_id):
    cr = db.makeup_credits.get(credit_id)
    if cr is None:
        errors.raise_error(errors.ERR_CREDIT_NOT_FOUND, "Credit not found")
    enr = db.enrollments.get(cr["enrollment_id"])
    if enr is None or enr["studio_id"] != studio_id:
        errors.raise_error(errors.ERR_CREDIT_NOT_FOUND, "Credit not found")
    return cr


def get_invoice(studio_id, invoice_id):
    inv = db.invoices.get(invoice_id)
    if inv is None:
        errors.raise_error(errors.ERR_INVOICE_NOT_FOUND, "Invoice not found")
    fam = db.families.get(inv["family_id"])
    if fam is None or fam["studio_id"] != studio_id:
        errors.raise_error(errors.ERR_INVOICE_NOT_FOUND, "Invoice not found")
    return inv


def get_payment(studio_id, payment_id):
    pay = db.payments.get(payment_id)
    if pay is None:
        errors.raise_error(errors.ERR_PAYMENT_NOT_FOUND, "Payment not found")
    fam = db.families.get(pay["family_id"])
    if fam is None or fam["studio_id"] != studio_id:
        errors.raise_error(errors.ERR_PAYMENT_NOT_FOUND, "Payment not found")
    return pay


def get_event(studio_id, event_id):
    return _scoped(db.recital_events, event_id, errors.ERR_EVENT_NOT_FOUND, studio_id)


def get_registration(studio_id, reg_id):
    reg = db.recital_registrations.get(reg_id)
    if reg is None:
        errors.raise_error(errors.ERR_REGISTRATION_NOT_FOUND, "Registration not found")
    ev = db.recital_events.get(reg["recital_event_id"])
    if ev is None or ev["studio_id"] != studio_id:
        errors.raise_error(errors.ERR_REGISTRATION_NOT_FOUND, "Registration not found")
    return reg


def get_rental(studio_id, rental_id):
    return _scoped(db.instrument_rentals, rental_id, errors.ERR_RENTAL_NOT_FOUND, studio_id)
