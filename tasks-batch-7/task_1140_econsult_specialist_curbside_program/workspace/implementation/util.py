"""Request-body validation, pagination parsing, and record serialization."""

import re

from flask import request

import clock
from errors import ApiError, ERR_INVALID_REQUEST

_ABSENT = object()

SPECIALTY_CODES = ("CARDIOLOGY", "ENDOCRINOLOGY", "NEUROLOGY", "DERMATOLOGY", "RHEUMATOLOGY")
PROVIDER_STATUSES = ("ACTIVE", "DEACTIVATED")
URGENCIES = ("ROUTINE", "URGENT")
DISPOSITIONS = ("MANAGE_IN_PRIMARY_CARE", "MANAGE_WITH_PLAN", "CONVERT_TO_VISIT")
RECORD_TYPES = ("PCP_NOTE", "SPECIALIST_NOTE")
VERDICTS = ("PASS", "REBUKE")

_NPI_RE = re.compile(r"^\d{10}$")
_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def invalid(message):
    raise ApiError(ERR_INVALID_REQUEST, 400, message)


def json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid("Request body must be a JSON object")
    return data


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_str(data, field, min_len=1):
    value = data.get(field, _ABSENT)
    if value is _ABSENT or not isinstance(value, str) or len(value) < min_len:
        invalid("Field '%s' is required and must be a string of length >= %d" % (field, min_len))
    return value


def opt_str(data, field, min_len=1):
    """For PATCH-style optional fields: absent -> None; present -> validated string."""
    value = data.get(field, _ABSENT)
    if value is _ABSENT:
        return None
    if not isinstance(value, str) or len(value) < min_len:
        invalid("Field '%s' must be a string of length >= %d" % (field, min_len))
    return value


def req_int(data, field, min_v=None, max_v=None):
    value = data.get(field, _ABSENT)
    if value is _ABSENT or not is_int(value):
        invalid("Field '%s' is required and must be an integer" % field)
    if min_v is not None and value < min_v:
        invalid("Field '%s' must be >= %d" % (field, min_v))
    if max_v is not None and value > max_v:
        invalid("Field '%s' must be <= %d" % (field, max_v))
    return value


def req_enum(data, field, allowed):
    value = data.get(field, _ABSENT)
    if value is _ABSENT or not isinstance(value, str) or value not in allowed:
        invalid("Field '%s' must be one of %s" % (field, ", ".join(allowed)))
    return value


def opt_enum(data, field, allowed, default=None):
    value = data.get(field, _ABSENT)
    if value is _ABSENT:
        return default
    if not isinstance(value, str) or value not in allowed:
        invalid("Field '%s' must be one of %s" % (field, ", ".join(allowed)))
    return value


def opt_bool(data, field, default=None):
    value = data.get(field, _ABSENT)
    if value is _ABSENT:
        return default
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean" % field)
    return value


def opt_str_list(data, field, default=None):
    value = data.get(field, _ABSENT)
    if value is _ABSENT:
        return default
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        invalid("Field '%s' must be a list of strings" % field)
    return list(value)


def req_datetime(data, field):
    value = data.get(field, _ABSENT)
    if value is _ABSENT:
        invalid("Field '%s' is required and must be an ISO 8601 timestamp" % field)
    try:
        return clock.parse_iso(value)
    except (ValueError, TypeError):
        invalid("Field '%s' must be an ISO 8601 timestamp" % field)


def req_npi(data, field="npi"):
    value = req_str(data, field)
    if not _NPI_RE.match(value):
        invalid("Field '%s' must be a 10-digit string" % field)
    return value


def req_period_key(data, field="period_key"):
    value = req_str(data, field)
    if not _PERIOD_RE.match(value):
        invalid("Field '%s' must be in YYYY-MM format" % field)
    return value


def pagination_params():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            invalid("Query parameter 'limit' must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid("Query parameter 'offset' must be an integer")
        if offset < 0:
            invalid("Query parameter 'offset' must be >= 0")
    return limit, offset


def sort_records(records):
    """created_at ascending, with insertion sequence as stable tie-break."""
    return sorted(records, key=lambda rec: (rec["created_at"], rec["_seq"]))


def paginate(records):
    limit, offset = pagination_params()
    ordered = sort_records(list(records))
    total = len(ordered)
    return ordered[offset:offset + limit], total, limit, offset


# ---------------------------------------------------------------------------
# Serializers: exact scaffold field sets; internal keys (``_``-prefixed) and
# datetimes are rendered as ISO 8601 UTC strings with three fractional digits.
# ---------------------------------------------------------------------------

_ENTITY_FIELDS = {
    "specialty_track": (
        ["id", "specialty_code", "response_time_target_hours", "urgent_target_hours",
         "base_response_fee_cents", "conversion_response_fee_cents",
         "clarification_fee_cents", "late_penalty_cents", "monthly_billing_cap_cents",
         "created_at", "updated_at", "version"],
        {"created_at", "updated_at"},
    ),
    "referring_provider": (
        ["id", "full_name", "npi", "status", "created_at", "updated_at", "version"],
        {"created_at", "updated_at"},
    ),
    "specialist": (
        ["id", "full_name", "npi", "status", "created_at", "updated_at", "version"],
        {"created_at", "updated_at"},
    ),
    "panel_membership": (
        ["id", "specialist_id", "specialty_track_id", "standing", "quality_score_bps",
         "reviews_count", "reviews_score_sum", "responded_count", "on_time_count",
         "rebuke_count", "expired_count", "open_consult_count",
         "provisional_balance_cents", "posted_balance_cents", "is_accepting",
         "unique_membership", "created_at", "updated_at", "version"],
        {"created_at", "updated_at"},
    ),
    "consult_request": (
        ["id", "referring_provider_id", "patient_ref", "specialty_track_id",
         "question_text", "icd10_primary", "comorbidity_flags", "urgency", "status",
         "billing_status", "assigned_specialist_id", "assigned_membership_id",
         "sla_due_at", "sla_breached", "clarification_rounds",
         "created_at", "updated_at", "version"],
        {"sla_due_at", "created_at", "updated_at"},
    ),
    "consult_response": (
        ["id", "consult_id", "specialist_id", "disposition", "recommendation_text",
         "on_time", "response_minutes", "pcp_note_documented",
         "specialist_note_documented", "documentation_complete", "review_required",
         "last_submitted_at", "revision_count", "status",
         "created_at", "updated_at", "version"],
        {"last_submitted_at", "created_at", "updated_at"},
    ),
    "clarification_message": (
        ["id", "consult_id", "author_role", "body", "sequence_no", "created_at"],
        {"created_at"},
    ),
    "in_person_conversion": (
        ["id", "consult_id", "specialist_id", "appointment_start", "appointment_end",
         "status", "created_at", "updated_at", "version"],
        {"appointment_start", "appointment_end", "created_at", "updated_at"},
    ),
    "quality_review": (
        ["id", "response_id", "reviewer_specialist_id", "timeliness_score",
         "appropriateness_score", "clarity_score", "composite_score_bps", "verdict",
         "status", "created_at", "updated_at", "version"],
        {"created_at", "updated_at"},
    ),
    "compensation_entry": (
        ["id", "membership_id", "consult_id", "entry_type", "amount_cents", "posture",
         "period_key", "created_at", "updated_at", "version"],
        {"created_at", "updated_at"},
    ),
    "availability_window": (
        ["id", "membership_id", "window_start", "window_end", "status",
         "created_at", "updated_at", "version"],
        {"window_start", "window_end", "created_at", "updated_at"},
    ),
    "billing_claim": (
        ["id", "consult_id", "claim_code", "amount_cents", "period_key", "status",
         "created_at", "updated_at", "version"],
        {"created_at", "updated_at"},
    ),
    "avoided_visit_measurement": (
        ["id", "specialty_track_id", "period_key", "responded_count",
         "conversions_count", "avoided_attributed_count", "avoided_conservative_count",
         "status", "created_at", "updated_at", "version"],
        {"created_at", "updated_at"},
    ),
    "routing_decision": (
        ["id", "consult_id", "outcome", "candidate_count", "selected_membership_id",
         "ranking_basis", "created_at"],
        {"created_at"},
    ),
}


def serialize(kind, rec):
    fields, dt_fields = _ENTITY_FIELDS[kind]
    out = {}
    for field in fields:
        value = rec.get(field)
        if field in dt_fields and value is not None:
            value = clock.fmt(value)
        out[field] = value
    return out


def serialize_list(kind, records):
    return [serialize(kind, rec) for rec in records]
