"""Shared infrastructure: in-memory store, logical clock, envelope, errors, auth,
validation helpers.  Storage is process-memory only and starts completely empty."""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# roles
# ---------------------------------------------------------------------------
ROLE_COORDINATOR = "AccreditationCoordinator"
ROLE_REVIEWER = "AccreditationBodyReviewer"
ROLE_INSPECTOR = "FdaInspector"
ROLE_QA = "QualityAssuranceOfficer"
ROLE_PHYSICIAN = "InterpretingPhysician"
ROLE_TECHNOLOGIST = "Technologist"
ROLE_PHYSICIST = "MedicalPhysicist"

ALL_ROLES = [
    ROLE_COORDINATOR,
    ROLE_REVIEWER,
    ROLE_INSPECTOR,
    ROLE_QA,
    ROLE_PHYSICIAN,
    ROLE_TECHNOLOGIST,
    ROLE_PHYSICIST,
]

ROLE_TO_ROLE_TYPE = {
    ROLE_PHYSICIAN: "INTERPRETING_PHYSICIAN",
    ROLE_TECHNOLOGIST: "TECHNOLOGIST",
    ROLE_PHYSICIST: "MEDICAL_PHYSICIST",
}

# ---------------------------------------------------------------------------
# error catalogue (error_id -> http status)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_ACTOR_NOT_AT_FACILITY": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_INTERPRETING_PHYSICIAN": 403,
    "ERR_STATE_POLICY_NOT_FOUND": 404,
    "ERR_FACILITY_NOT_FOUND": 404,
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_PERSONNEL_NOT_FOUND": 404,
    "ERR_SURVEY_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_SUBMISSION_NOT_FOUND": 404,
    "ERR_EXAM_NOT_FOUND": 404,
    "ERR_LETTER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_FAILURE_EVENT_NOT_FOUND": 404,
    "ERR_REPEAT_RECORD_NOT_FOUND": 404,
    "ERR_AUDIT_CYCLE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_STALE_UNIT_VERSION": 412,
    "ERR_STALE_EXAM_VERSION": 412,
    "ERR_SURVEY_NOT_DECIDABLE": 409,
    "ERR_SUBMISSION_NOT_REVIEWABLE": 409,
    "ERR_SUBMISSION_NOT_REVISABLE": 409,
    "ERR_SUBMISSION_NOT_WITHDRAWABLE": 409,
    "ERR_INSPECTION_ALREADY_CLOSED": 409,
    "ERR_LETTER_NOT_SENDABLE": 409,
    "ERR_LETTER_NOT_SENT": 409,
    "ERR_ORDER_NOT_DETERMINABLE": 409,
    "ERR_ORDER_NOT_SCHEDULABLE": 409,
    "ERR_ORDER_NOT_COMPLETABLE": 409,
    "ERR_EXAM_NOT_INTERPRETABLE": 409,
    "ERR_EXAM_NOT_AMENDABLE": 409,
    "ERR_OUTCOME_ALREADY_RECORDED": 409,
    "ERR_AUDIT_CYCLE_NOT_CLOSABLE": 409,
    "ERR_FAILURE_ALREADY_RESOLVED": 409,
    "ERR_REPEAT_RECORD_ALREADY_RETRACTED": 409,
    "ERR_UNIT_NOT_IN_SERVICE": 409,
    "ERR_FACILITY_SUSPENDED": 409,
    "ERR_TECHNOLOGIST_NOT_QUALIFIED": 422,
    "ERR_PHYSICIAN_NOT_QUALIFIED": 422,
    "ERR_MODALITY_NOT_CERTIFIED": 422,
    "ERR_UNIT_ACCREDITATION_SUSPENDED": 409,
    "ERR_OPEN_LEVEL_1_FINDING": 409,
    "ERR_POST_REPAIR_SURVEY_MISSING": 409,
    "ERR_EXAM_UNIT_MISMATCH": 422,
    "ERR_PACKET_EXAM_NOT_FINAL": 422,
    "ERR_PACKET_TOO_SMALL": 422,
    "ERR_FAILURE_UNIT_MISMATCH": 422,
    "ERR_NOT_AN_INTERPRETING_PHYSICIAN": 422,
    "ERR_FUTURE_TIMESTAMP": 422,
    "ERR_SURVEY_WINDOW_INVALID": 422,
    "ERR_SURVEY_WINDOW_OVERLAP": 409,
    "ERR_REACCREDITATION_WINDOW_CLOSED": 409,
    "ERR_AUDIT_PERIOD_NOT_ELAPSED": 409,
    "ERR_APPOINTMENT_IN_PAST": 422,
    "ERR_CLOCK_REWIND": 422,
    "ERR_REACCREDITATION_ATTEMPTS_EXHAUSTED": 409,
    "ERR_SUBMISSION_ALREADY_OPEN": 409,
    "ERR_AUDIT_CYCLE_OVERLAP": 409,
    "ERR_AMENDMENT_NO_CHANGE": 422,
    "ERR_DENSITY_CATEGORY_REQUIRED": 422,
    "ERR_EXAM_NOT_ELIGIBLE_FOR_SUPPLEMENTAL": 422,
    "ERR_COVERAGE_NOT_DETERMINED": 409,
    "ERR_SUPPLEMENTAL_CAPACITY_CONFLICT": 409,
    "ERR_INVALID_DEPOSIT_AMOUNT": 422,
    "ERR_INSUFFICIENT_PREPAID_CREDIT": 402,
    # transport-level fallbacks (not part of the declared catalog)
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id.replace("ERR_", "").replace("_", " ").lower()


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------
EPOCH_DEFAULT = "2026-08-01T00:00:00Z"


def parse_dt(value):
    """Parse an ISO-8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_dt(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return "%s.%03dZ" % (value.strftime("%Y-%m-%dT%H:%M:%S"), value.microsecond // 1000)


def plus_days(value, days):
    return value + timedelta(days=days)


def round2(numerator, denominator):
    """round_half_up(100 * numerator / denominator, 2) as a float."""
    quotient = Decimal(numerator) * Decimal(100) / Decimal(denominator)
    return float(quotient.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def cents_half_up(amount, rate):
    value = Decimal(int(amount)) * Decimal(str(rate))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dsum(values):
    total = Decimal("0")
    for value in values:
        total += Decimal(str(value))
    if total == total.to_integral_value():
        return int(total)
    return float(total)


# ---------------------------------------------------------------------------
# in-memory store
# ---------------------------------------------------------------------------
KINDS = (
    "state_policy",
    "facility",
    "unit",
    "personnel",
    "credit",
    "survey",
    "inspection",
    "submission",
    "exam",
    "letter",
    "order",
    "failure",
    "repeat",
    "cycle",
)

NO_VERSION_KINDS = {"credit"}


class Store(object):
    def __init__(self):
        self.tables = dict((kind, {}) for kind in KINDS)
        self.seq = 0
        self.clock = parse_dt(EPOCH_DEFAULT)
        self.clock_display = EPOCH_DEFAULT

    def next_seq(self):
        self.seq += 1
        return self.seq

    def table(self, kind):
        return self.tables[kind]

    def all(self, kind):
        return list(self.tables[kind].values())

    def get(self, kind, oid):
        if not isinstance(oid, str):
            return None
        return self.tables[kind].get(oid)


DB = Store()


def now():
    return DB.clock


def new_entity(kind, fields):
    entity = dict(fields)
    entity["id"] = str(uuid.uuid4())
    entity["created_at"] = DB.clock
    if kind not in NO_VERSION_KINDS:
        entity["updated_at"] = DB.clock
        entity["version"] = 1
    entity["_kind"] = kind
    entity["_seq"] = DB.next_seq()
    DB.tables[kind][entity["id"]] = entity
    touched = getattr(g, "touched", None)
    if touched is not None:
        touched.add((kind, entity["id"]))
    return entity


def touch(entity):
    """Refresh updated_at and bump version, at most once per request."""
    if entity is None or entity["_kind"] in NO_VERSION_KINDS:
        return
    key = (entity["_kind"], entity["id"])
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    if key in touched:
        return
    touched.add(key)
    entity["updated_at"] = DB.clock
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# serialisation
# ---------------------------------------------------------------------------
FIELDS = {
    "state_policy": [
        "state_code", "density_notice_rule", "lay_summary_max_reading_grade",
        "lay_summary_deadline_days", "required_notice_codes",
        "supplemental_coverage_mandate",
        "supplemental_cost_share_waiver_threshold_cents", "followup_grace_days",
        "report_turnaround_days", "urgent_report_turnaround_days", "ce_grace_days",
    ],
    "facility": [
        "name", "state_policy_id", "accreditation_body",
        "supplemental_concurrent_capacity", "total_funded_cents",
        "prepaid_credit_cents", "fee_held_cents", "fee_consumed_cents",
        "compliance_posture", "open_notice_obligations", "last_compliance_run_at",
    ],
    "unit": [
        "facility_id", "manufacturer", "model_serial", "modality",
        "accreditation_status", "operational_state", "accreditation_expires_on",
        "reaccreditation_attempts_remaining", "survey_compliance",
        "last_passed_survey_end", "total_images_acquired", "repeat_images_acquired",
        "image_based_repeat_rate_pct", "patient_based_repeat_rate_pct",
        "repeat_rate_flag",
    ],
    "personnel": [
        "facility_id", "full_name", "role_type", "initial_qualification_on",
        "initial_training_hours", "initial_read_volume", "modality_certifications",
        "qualification_status", "ce_status", "ce_hours_36mo", "volume_credit_24mo",
        "ce_deadline_at", "last_qualification_review_at",
    ],
    "credit": [
        "personnel_id", "credit_type", "ce_hours", "exam_count", "modality",
        "awarded_on", "source_note",
    ],
    "survey": [
        "unit_id", "physicist_id", "survey_type", "status", "phantom_score",
        "mean_glandular_dose_mgy", "critical_deficiency_codes", "effective_start",
        "effective_end", "decided_at", "remediation_attempts", "outcome_note",
    ],
    "inspection": [
        "facility_id", "inspection_date", "inspector_findings_level",
        "finding_codes", "status", "corrective_action_due_at", "closed_at",
    ],
    "submission": [
        "unit_id", "exam_ids", "attempt_number", "status", "fee_held_cents",
        "review_decision", "deficiency_categories", "submitted_at", "reviewed_at",
        "reviewer_note",
    ],
    "exam": [
        "unit_id", "technologist_id", "interpreting_physician_id", "patient_ref",
        "patient_state_code", "exam_type", "performed_at", "original_image_count",
        "report_status", "notification_status", "follow_up_status",
        "birads_assessment", "density_category", "recall_flag", "biopsy_performed",
        "pathology_result", "outcome_recorded_at", "repeat_image_count",
        "report_due_at", "interpreted_at", "interpreted_late",
        "notification_deadline_at", "amendment_count",
    ],
    "letter": [
        "exam_id", "supersedes_letter_id", "letter_type", "status",
        "required_notice_codes", "density_statement_code", "reading_grade_level",
        "deadline_at", "governing_state_code", "dispatch_channel", "generated_at",
        "sent_at", "undeliverable_reason",
    ],
    "order": [
        "exam_id", "modality", "status", "coverage_outcome", "allowed_amount_cents",
        "covered_amount_cents", "patient_responsibility_cents", "coverage_tier",
        "governing_state_code", "recommended_at", "followup_due_at",
        "appointment_start", "appointment_end", "completed_at",
        "external_referral_note",
    ],
    "failure": [
        "unit_id", "failure_code", "severity", "detected_at", "status",
        "requires_post_repair_survey", "resolved_at", "repair_note",
    ],
    "repeat": [
        "exam_id", "equipment_failure_id", "reason_code", "repeat_image_count",
        "retracted", "retraction_reason", "documented_at",
    ],
    "cycle": [
        "radiologist_id", "period_start", "period_end", "status",
        "variant_at_close", "followup_window_days", "screening_exam_count",
        "recall_count", "biopsy_count", "cancer_count", "excluded_exam_count",
        "recall_rate_pct", "ppv_pct", "abnormal_interpretation_flag", "locked_at",
    ],
}


def serialize(entity):
    if entity is None:
        return None
    kind = entity["_kind"]
    out = {"id": entity["id"]}
    for name in FIELDS[kind]:
        value = entity.get(name)
        out[name] = fmt_dt(value) if isinstance(value, datetime) else value
    out["created_at"] = fmt_dt(entity["created_at"])
    if kind not in NO_VERSION_KINDS:
        out["updated_at"] = fmt_dt(entity["updated_at"])
        out["version"] = entity["version"]
    return out


# ---------------------------------------------------------------------------
# envelope
# ---------------------------------------------------------------------------
def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(DB.clock),
    }


def ok_object(payload, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": payload,
    }
    return jsonify(body), status


def ok_entity(entity, status=200):
    return ok_object(serialize(entity), status)


def ok_list(rows, status=200):
    limit, offset = read_pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(page) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(row) for row in page],
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def read_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        limit = _positive_int(limit_raw, "limit")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_raw is not None:
        offset = _positive_int(offset_raw, "offset")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be greater than or equal to 0")
    return limit, offset


def _positive_int(raw, name):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)


def sort_rows(rows):
    return sorted(rows, key=lambda row: (row["created_at"], row["_seq"]))


def filter_rows(rows, mapping):
    """mapping: query-param -> field name (string equality)."""
    out = rows
    for param, field in mapping.items():
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        if field in ("retracted", "requires_post_repair_survey", "recall_flag",
                     "interpreted_late", "repeat_rate_flag", "biopsy_performed"):
            lowered = raw.strip().lower()
            if lowered in ("true", "1"):
                wanted = True
            elif lowered in ("false", "0"):
                wanted = False
            else:
                return []
            out = [row for row in out if bool(row.get(field)) is wanted]
        else:
            out = [row for row in out if row.get(field) == raw]
    return out


# ---------------------------------------------------------------------------
# auth (validation ladder priorities 1 and 2)
# ---------------------------------------------------------------------------
def endpoint(roles):
    allowed = list(roles)

    def decorator(handler):
        @wraps(handler)
        def wrapper(**kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not user_id.strip():
                fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
            if not role or not role.strip():
                fail("ERR_UNAUTHENTICATED", "X-User-Role header is required")
            role = role.strip()
            if role not in ALL_ROLES:
                fail("ERR_UNAUTHENTICATED", "unrecognised role")
            g.user_id = user_id.strip()
            g.role = role
            if role not in allowed:
                fail("ERR_FORBIDDEN_ROLE", "role %s may not call this endpoint" % role)
            return handler(**kwargs)

        return wrapper

    return decorator


def actor_personnel(role_type=None):
    """Personnel row identified by X-User-ID, optionally restricted by role_type."""
    for person in DB.all("personnel"):
        if person["id"] == g.user_id:
            if role_type is not None and person["role_type"] != role_type:
                return None
            return person
    return None


def require_actor_at_facility(facility_id, role_type=None):
    """Ladder priority 3: the acting user must be personnel of the facility."""
    person = actor_personnel(role_type)
    if person is None:
        fail("ERR_ACTOR_NOT_AT_FACILITY", "acting user is not personnel of this facility")
    if facility_id is not None and person["facility_id"] != facility_id:
        fail("ERR_ACTOR_NOT_AT_FACILITY", "acting user is not personnel of this facility")
    return person


# ---------------------------------------------------------------------------
# body / schema validation (ladder priority 20)
# ---------------------------------------------------------------------------
MISSING = object()


def body_dict():
    """Parse the JSON body lazily so that auth failures outrank parse failures."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return payload


def _bad(name, detail):
    fail("ERR_INVALID_REQUEST", "%s %s" % (name, detail))


def _present(body, name, required):
    if name not in body or body[name] is None:
        if required:
            _bad(name, "is required")
        return False
    return True


def v_str(body, name, required=True, min_len=1, max_len=None, default=MISSING):
    if not _present(body, name, required):
        return None if default is MISSING else default
    value = body[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if min_len is not None and len(value) < min_len:
        _bad(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters" % max_len)
    return value


def v_enum(body, name, allowed, required=True, default=MISSING):
    if not _present(body, name, required):
        return None if default is MISSING else default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def v_int(body, name, required=True, minimum=None, maximum=None, default=MISSING):
    if not _present(body, name, required):
        return None if default is MISSING else default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be greater than or equal to %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be less than or equal to %s" % maximum)
    return value


def v_num(body, name, required=True, minimum=None, maximum=None, default=MISSING):
    if not _present(body, name, required):
        return None if default is MISSING else default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    if minimum is not None and value < minimum:
        _bad(name, "must be greater than or equal to %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be less than or equal to %s" % maximum)
    return value


def v_bool(body, name, required=True, default=MISSING):
    if not _present(body, name, required):
        return None if default is MISSING else default
    value = body[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def v_dt(body, name, required=True, default=MISSING):
    if not _present(body, name, required):
        return None if default is MISSING else default
    value = body[name]
    if not isinstance(value, str):
        _bad(name, "must be an ISO-8601 timestamp")
    parsed = parse_dt(value)
    if parsed is None:
        _bad(name, "must be an ISO-8601 timestamp")
    return parsed


def v_str_list(body, name, required=True, allowed=None, default=MISSING):
    if not _present(body, name, required):
        return None if default is MISSING else (list(default) if isinstance(default, list) else default)
    value = body[name]
    if not isinstance(value, list):
        _bad(name, "must be an array of strings")
    for item in value:
        if not isinstance(item, str):
            _bad(name, "must be an array of strings")
        if allowed is not None and item not in allowed:
            _bad(name, "entries must be one of %s" % ", ".join(allowed))
    return list(value)


def v_state_code(body, name, required=True):
    value = v_str(body, name, required=required, min_len=None)
    if value is None:
        return None
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        _bad(name, "must be exactly two uppercase letters")
    return value


def v_id(body, name, required=True, default=MISSING):
    return v_str(body, name, required=required, min_len=1, default=default)


def v_expected_version(body, name):
    if name not in body or body[name] is None:
        _bad(name, "is required")
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    return value
