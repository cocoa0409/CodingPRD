"""Shared helpers: body validation, pagination, entity stamps, serializers."""

import uuid

from flask import request

import db
import derived
import errors
from clock import iso_ms, parse_iso
from state import CLOCK

# ---------------------------------------------------------------------------
# Enum domains (SCAFFOLD §1.1)
# ---------------------------------------------------------------------------

UNIT_CATEGORIES = {"INPATIENT", "EMERGENCY", "OUTPATIENT", "SURGICAL", "ICU", "OTHER"}
UNIT_POSTURES = {"STANDARD", "RESTRICTED"}
CAPABILITIES = {"ADVOCATE", "INVESTIGATOR", "QRO", "DIRECTOR"}
CHANNELS = {"PHONE", "EMAIL", "PORTAL", "IN_PERSON", "LETTER"}
GRIEVANCE_CATEGORIES = {
    "BILLING",
    "CARE_QUALITY",
    "STAFF_CONDUCT",
    "ACCESS_DELAY",
    "RIGHTS_ABUSE",
    "COMMUNICATION",
    "OTHER",
}
SEVERITY_TIERS = {"STANDARD", "URGENT", "CRITICAL"}
DECISIONS = {"COMPLAINT", "GRIEVANCE"}
RATIONALE_CODES = {
    "INITIAL_INTAKE",
    "PATIENT_REQUEST",
    "ESCALATION_OF_CONCERN",
    "REGULATORY_REVIEW",
    "DIRECTOR_OVERRIDE",
}
ASSIGNMENT_ROLES = {"PRIMARY", "SUPPORTING"}
NOTE_TYPES = {"INTERVIEW", "DOCUMENT_REVIEW", "SITE_VISIT", "PHONE_CALL"}
LETTER_SECTIONS = {
    "PATIENT_SUMMARY",
    "INVESTIGATION_STEPS",
    "FINDINGS",
    "RESOLUTION",
    "CONTACT_INFO",
    "RISK_DISCLOSURE",
    "QAPI_REFERENCE",
}
LETTER_BASE_REQUIRED = {
    "PATIENT_SUMMARY",
    "INVESTIGATION_STEPS",
    "FINDINGS",
    "RESOLUTION",
    "CONTACT_INFO",
}
RECOVERY_ACTION_TYPES = {
    "MEAL_VOUCHER",
    "PARKING_COMP",
    "BILL_ADJUSTMENT",
    "GOODWILL_GESTURE",
    "EXPEDITED_APPOINTMENT",
}
ESCALATION_TYPES = {"CARE_CONCERN", "SYSTEMIC"}
REVIEW_TRACKS = {"COMPLIANCE", "SAFETY", "BOTH"}
REVIEW_BRANCHES = {"COMPLIANCE", "SAFETY"}
ADJUDICATION_OUTCOMES = {"SUBSTANTIATED", "UNSUBSTANTIATED"}
AUTHORITY_CODES = {"STATE_HEALTH_DEPT", "CMS_REGIONAL", "ACCREDITATION_BODY"}
TRIGGER_REASONS = {"ALLEGED_ABUSE", "SUBSTANTIATED_CARE_CONCERN", "SYSTEMIC_ISSUE"}
SUSPENSION_REASONS = {
    "AWAITING_PATIENT",
    "AWAITING_FAMILY",
    "AWAITING_RECORDS",
    "LANGUAGE_ACCESS",
}

RECOVERY_CASE_CAP_CENTS = 50000

_MISSING = object()


# ---------------------------------------------------------------------------
# Request body primitives (validation precedence per PRD §2.6)
# ---------------------------------------------------------------------------


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


def require_present(body, *names):
    """Missing required fields are reported at 400 before dependent FK checks."""
    for name in names:
        if name not in body or body[name] is None:
            raise errors.invalid_request(f"Missing required field: {name}")


def check_string(body, name, required=False, default=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {name}")
        return default
    if not isinstance(value, str) or value == "":
        raise errors.invalid_request(f"Field {name} must be a non-empty string")
    return value


def check_bool(body, name, default=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, bool):
        raise errors.invalid_request(f"Field {name} must be a boolean")
    return value


def check_int(body, name, minimum=None, default=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request(f"Field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise errors.invalid_request(f"Field {name} must be >= {minimum}")
    return value


def check_enum(body, name, allowed, required=False, default=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {name}")
        return default
    if not isinstance(value, str) or value not in allowed:
        raise errors.invalid_enum(f"Field {name} has an invalid value: {value}")
    return value


def check_datetime(body, name, required=False):
    """Parse an ISO datetime body field; unparseable -> ERR_INVALID_REQUEST."""
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {name}")
        return None
    dt = parse_iso(value)
    if dt is None:
        raise errors.invalid_request(f"Field {name} is not a valid ISO 8601 timestamp")
    return dt


def parse_pagination():
    """limit/offset per SCAFFOLD §1.0 pagination_defaults (10 / min 1 / max 100 / 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise errors.invalid_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise errors.invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise errors.invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise errors.invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total


def parse_bool_query(name):
    raw = request.args.get(name)
    if raw is None:
        return _MISSING
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    raise errors.invalid_request(f"Query parameter {name} must be true or false")


# ---------------------------------------------------------------------------
# Entity construction / mutation (PRD §2.5 common quartet)
# ---------------------------------------------------------------------------


def new_id():
    return str(uuid.uuid4())


def stamp_new():
    return {
        "id": new_id(),
        "created_at": CLOCK.now_iso(),
        "updated_at": CLOCK.now_iso(),
        "version": 1,
        "_seq": db.next_sequence(),
    }


def stamp_light():
    """Immutable records carry only id and created_at (PRD §2.5)."""
    return {
        "id": new_id(),
        "created_at": CLOCK.now_iso(),
        "_seq": db.next_sequence(),
    }


def touch(entity):
    """Refresh updated_at and bump version on every mutation (incl. cascades)."""
    entity["updated_at"] = CLOCK.now_iso()
    entity["version"] += 1


def sorted_by_creation(items):
    return sorted(items, key=lambda item: item["_seq"])


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Serializers (derived fields folded in on every read)
# ---------------------------------------------------------------------------


def serialize_unit(unit):
    out = public(unit)
    out["open_case_count"] = derived.unit_open_case_count(unit["id"])
    out["late_filed_event_count"] = derived.unit_late_filed_event_count(unit["id"])
    return out


def serialize_staff(staff):
    out = public(staff)
    out["open_assignment_count"] = derived.staff_open_assignment_count(staff["id"])
    return out


def serialize_holiday(holiday):
    return public(holiday)


def serialize_case(case):
    out = public(case)
    now = CLOCK.now()
    cal_due, biz_due, tolling = derived.response_dues(case, now)
    out["response_due_calendar_at"] = iso_ms(cal_due) if cal_due else None
    out["response_due_business_at"] = iso_ms(biz_due) if biz_due else None
    out["tolling_credit_seconds"] = tolling
    out["regulatory_clock_status"] = derived.regulatory_clock_status(case, now)
    out["priority_score"] = derived.priority_score(case, now)
    out["requires_qro_cosign"] = derived.requires_qro_cosign(case)
    out["outstanding_recovery_cents"] = derived.outstanding_recovery_cents(case["id"])
    return out


def serialize_decision(decision):
    return public(decision)


def serialize_assignment(assignment):
    return public(assignment)


def serialize_investigation(investigation):
    out = public(investigation)
    total, interviews = derived.investigation_note_counts(investigation["id"])
    out["note_count"] = total
    out["interview_note_count"] = interviews
    return out


def serialize_note(note):
    return public(note)


def serialize_letter(letter):
    return public(letter)


def serialize_recovery(action):
    return public(action)


def serialize_escalation(escalation):
    return public(escalation)


def serialize_event(event):
    out = public(event)
    out["filing_deadline_at"] = iso_ms(derived.event_filing_deadline(event))
    return out


def serialize_rounding(session):
    return public(session)


def serialize_room(room):
    return public(room)


def serialize_booking(booking):
    return public(booking)


def serialize_followup(followup):
    out = public(followup)
    out["status"] = derived.followup_status(followup)
    out["due_at"] = iso_ms(derived.followup_due_at(followup))
    out["expires_at"] = iso_ms(derived.followup_expires_at(followup))
    return out


def serialize_suspension(suspension):
    return public(suspension)


def serialize_snapshot(snapshot):
    return public(snapshot)
