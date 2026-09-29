"""Request-body shape validation (precedence check 4) and enum catalogues."""

from decimal import Decimal, ROUND_HALF_UP

from flask import request

import clock
from errors import fail

# ---------------------------------------------------------------- enumerations

STATE_CODES = ("WA", "NV", "CT", "CA", "TX")
ENTITY_STATUS_CLAIMS = ("COVERED_ENTITY", "BUSINESS_ASSOCIATE", "NOT_COVERED")
SOURCE_KINDS = ("USER_PROVIDED", "DEVICE_SENSOR", "THIRD_PARTY", "DERIVED_INFERENCE")
HEALTH_SIGNAL_KINDS = (
    "DIAGNOSIS", "TREATMENT", "MEASUREMENT", "REPRODUCTIVE",
    "PRECISE_LOCATION", "BIOMETRIC", "NON_HEALTH",
)
DIRECT_HEALTH_SIGNALS = ("DIAGNOSIS", "TREATMENT", "MEASUREMENT", "REPRODUCTIVE", "BIOMETRIC")
PURPOSE_KINDS = ("PRIMARY_SERVICE", "ANALYTICS", "ADVERTISING", "RESEARCH", "SALE")
ACTIVITY_KINDS = ("COLLECT", "SHARE", "SELL")
DISCLOSURE_SPECIFICITIES = ("ELEMENT_NAMED", "CATEGORY_NAMED")
AGE_BANDS = ("ADULT", "MINOR_13_16", "UNDER_13")
SPECIFICITY_MODES = ("ELEMENT_LEVEL", "CATEGORY_LEVEL")
REQUEST_KINDS = ("ACCESS", "DELETE", "CONFIRM")
SUBMITTED_CHANNELS = ("IN_APP", "EMAIL", "WEB_FORM")
VENDOR_KINDS = ("PROCESSOR", "THIRD_PARTY_RECIPIENT", "PURCHASER")
FACILITY_KINDS = ("SENSITIVE_HEALTH", "GENERAL_HEALTH", "NON_HEALTH")
BREACH_SCOPES = ("CHD_ONLY", "GENERAL_PII_ONLY", "MIXED")
PROTECTION_STATES = ("UNPROTECTED", "ENCRYPTED_SECURED")
CONSENT_AXES = ("COLLECT", "SHARE", "SELL")

APPLICABILITY_STATUSES = ("UNDETERMINED", "HIPAA_ONLY", "DUAL_TRACK", "CHD_REGULATED")
REGULATED_SCOPES = ("NONE", "PARTIAL", "FULL")

# ------------------------------------------- computed / system field catalogue

COMMON_FORBIDDEN = ("id", "created_at", "updated_at", "version")

COMPUTED_FIELDS = {
    "AppProduct": (
        "small_business_flag", "applicability_status", "regulated_scope",
        "active_element_count", "regulated_element_count", "compliance_deadline_date",
        "active_share_consent_count", "exposure_cents", "policy_compliance_state",
        "security_program_state",
    ),
    "ApplicabilityAssessment": (
        "determination", "regulated_element_count_snapshot", "active_element_count_snapshot",
        "regulated_scope", "compliance_deadline_date", "state", "revision_count",
        "submitted_by_user_id", "approved_by_user_id", "return_reason",
    ),
    "DataElement": ("inference_depth", "chd_classification", "status", "retired_reason"),
    "ProcessingPurpose": (
        "consent_axis", "requires_separate_consent", "third_party_disclosure_required",
    ),
    "ElementPurposeMapping": ("status", "suspension_reason", "regulated_flag"),
    "Consumer": ("verification_token", "deletion_completed_count"),
    "ConsentRecord": (
        "collection_state", "sharing_state", "sale_state", "record_state",
        "collection_granted_at", "sharing_granted_at", "sale_authorized_at",
        "last_withdrawn_axis", "last_withdrawn_at", "processing_halt_deadline_at",
    ),
    "PrivacyPolicyVersion": (
        "effective_to", "completeness_score", "gap_count", "state",
        "authored_by_user_id", "published_by_user_id",
    ),
    "ConsumerRequest": (
        "received_at", "state", "verification_rounds_used", "verification_window_ends_at",
        "verified_at", "extension_granted", "response_deadline_at",
        "outstanding_task_count", "denial_reason",
    ),
    "DeletionTask": (
        "hop_distance", "state", "attempt_count", "due_at", "confirmed_at", "failure_reason",
    ),
    "Vendor": ("agreement_state", "agreement_compliance", "executed_at", "terminated_at"),
    "GeofenceZone": ("prohibition_rule", "min_standoff_meters", "last_campaign_activated_at"),
    "GeofenceCampaign": ("standoff_meters", "state", "pause_reason"),
    "BreachIncident": (
        "state", "health_rule_deadline_at", "general_rule_deadline_at",
        "governing_deadline_at", "media_notice_required", "notified_at",
        "exposure_contribution_cents",
    ),
    "SecurityRiskAssessment": ("residual_risk_score", "risk_tier", "state", "finalized_at"),
}

# -------------------------------------------------------------- body plumbing


def raw_body():
    """Parse the JSON body. A body-less request is treated as an empty object."""
    data = request.get_data(cache=True)
    if data is None or not str(data).strip() or not data.strip():
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return parsed


class F(object):
    """One declared body field."""

    def __init__(self, kind, required=True, members=None, minimum=None,
                 maximum=None, default=None, nullable=False):
        self.kind = kind
        self.required = required
        self.members = members
        self.minimum = minimum
        self.maximum = maximum
        self.default = default
        self.nullable = nullable


def _bad(name):
    fail("ERR_INVALID_REQUEST", "Field '%s' is missing or malformed." % name)


def _check_one(name, spec, value):
    if value is None:
        if spec.nullable:
            return None
        _bad(name)
    kind = spec.kind
    if kind == "string":
        if not isinstance(value, str):
            _bad(name)
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in spec.members:
            _bad(name)
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad(name)
        if spec.minimum is not None and value < spec.minimum:
            _bad(name)
        if spec.maximum is not None and value > spec.maximum:
            _bad(name)
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad(name)
        if spec.minimum is not None and value < spec.minimum:
            _bad(name)
        if spec.maximum is not None and value > spec.maximum:
            _bad(name)
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            _bad(name)
        return value
    if kind == "datetime":
        parsed = clock.parse_dt(value)
        if parsed is None:
            _bad(name)
        return parsed
    if kind == "date":
        parsed = clock.parse_date(value)
        if parsed is None:
            _bad(name)
        return parsed
    if kind == "enum_list":
        if not isinstance(value, list):
            _bad(name)
        for item in value:
            if not isinstance(item, str) or item not in spec.members:
                _bad(name)
        return list(value)
    _bad(name)


def parse(entity, fields, extra_allowed=()):
    """Validate the body against `fields`, rejecting the entity's computed fields.

    `fields` maps a body field name to an `F` spec. Returns a dict carrying every
    declared field that was supplied (plus defaults for absent optional fields
    whose spec declares one).
    """
    payload = raw_body()
    declared = set(fields.keys()) | set(extra_allowed)
    forbidden = set(COMMON_FORBIDDEN) | set(COMPUTED_FIELDS.get(entity, ()))
    forbidden -= declared
    for key in payload.keys():
        if key in forbidden:
            fail("ERR_INVALID_REQUEST",
                 "Field '%s' is computed by the server and may not be supplied." % key)

    out = {}
    for name, spec in fields.items():
        if name not in payload:
            if spec.required:
                _bad(name)
            if spec.default is not None:
                out[name] = spec.default
            continue
        out[name] = _check_one(name, spec, payload[name])
    return out


def supplied(entity, fields):
    """Like parse() but only returns the keys the client actually supplied."""
    payload = raw_body()
    declared = set(fields.keys())
    forbidden = set(COMMON_FORBIDDEN) | set(COMPUTED_FIELDS.get(entity, ()))
    forbidden -= declared
    for key in payload.keys():
        if key in forbidden:
            fail("ERR_INVALID_REQUEST",
                 "Field '%s' is computed by the server and may not be supplied." % key)
    out = {}
    for name, spec in fields.items():
        if name in payload:
            out[name] = _check_one(name, spec, payload[name])
    return out


def no_body(entity, extra_allowed=()):
    """For action endpoints that declare no input fields."""
    return parse(entity, {}, extra_allowed)


def quantize_ratio(value):
    """hipaa_covered_transaction_ratio: stored with exactly two decimal places."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
