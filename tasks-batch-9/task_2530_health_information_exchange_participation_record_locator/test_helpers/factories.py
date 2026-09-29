"""Payload builders with PRD-valid defaults.

Each builder returns a plain dict that satisfies every schema rule the PRD states
for that operation, and accepts keyword overrides so a test can perturb exactly
one field. Passing ``None`` for an optional field transmits an explicit null;
omit the keyword entirely to leave the default in place.
"""

from typing import Any, Dict, List, Optional

# ----------------------------------------------------------------------
# Reference tuning generation
# ----------------------------------------------------------------------
# The six weights below sum to exactly 1.0000, which the PRD requires within an
# absolute tolerance of 0.0001. They are the reference weight family used by
# every matching test that does not deliberately alter a weight.
REFERENCE_WEIGHTS: Dict[str, float] = {
    "weight_family_name": 0.20,
    "weight_given_name": 0.12,
    "weight_birth_date": 0.25,
    "weight_ssn_last4": 0.28,
    "weight_postal_code": 0.08,
    "weight_phone_digits": 0.07,
}
REFERENCE_AUTO_LINK_THRESHOLD = 0.9200
REFERENCE_REVIEW_LOWER_BOUND = 0.7500
REFERENCE_PARTIAL_CREDIT_FACTOR = 0.50


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    base.update(overrides)
    return base


# ----------------------------------------------------------------------
# Participants
# ----------------------------------------------------------------------

def participant_payload(
    legal_name: str = "Alto Mesa Hospital",
    org_type: str = "HOSPITAL",
    declared_annual_patient_volume: int = 96000,
    primary_contact_email: str = "hie@altomesa.example",
    **overrides,
) -> Dict[str, Any]:
    """A registrable participant. Volume 96,000 gives a monthly basis of 8,000 units."""
    return _merge(
        {
            "legal_name": legal_name,
            "org_type": org_type,
            "declared_annual_patient_volume": declared_annual_patient_volume,
            "primary_contact_email": primary_contact_email,
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Conformance runs
# ----------------------------------------------------------------------

def conformance_test_payload(
    profile: str = "QUERY_RESPONDER",
    scheduled_start: str = "2026-08-01T09:00:00Z",
    scheduled_end: str = "2026-08-01T17:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    """A bookable sandbox window; `scheduled_end` is strictly later than the start."""
    return _merge(
        {
            "profile": profile,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
        },
        overrides,
    )


def conformance_result_payload(
    assertions_total: int = 200,
    assertions_passed: int = 200,
    failure_categories: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """A perfect run: pass rate 1.0000 with no failure categories."""
    payload: Dict[str, Any] = {
        "assertions_total": assertions_total,
        "assertions_passed": assertions_passed,
    }
    if failure_categories is not None:
        payload["failure_categories"] = failure_categories
    return _merge(payload, overrides)


# ----------------------------------------------------------------------
# Governance generations
# ----------------------------------------------------------------------

def consent_policy_payload(
    policy_version: str = "SP-2026.1",
    model: str = "OPT_IN",
    sensitive_categories_segmented: Optional[List[str]] = None,
    default_share_for_treatment: bool = True,
    effective_from: str = "2026-01-01T00:00:00Z",
    effective_until: Any = None,
    **overrides,
) -> Dict[str, Any]:
    """An open-ended statewide policy generation covering the default clock."""
    payload: Dict[str, Any] = {
        "policy_version": policy_version,
        "model": model,
        "sensitive_categories_segmented": (
            ["BEHAVIORAL_HEALTH", "HIV", "SUD", "REPRODUCTIVE"]
            if sensitive_categories_segmented is None
            else sensitive_categories_segmented
        ),
        "default_share_for_treatment": default_share_for_treatment,
        "effective_from": effective_from,
    }
    if effective_until is not None:
        payload["effective_until"] = effective_until
    return _merge(payload, overrides)


def threshold_config_payload(
    config_label: str = "REF-PROB-V1",
    auto_link_threshold: float = REFERENCE_AUTO_LINK_THRESHOLD,
    review_lower_bound: float = REFERENCE_REVIEW_LOWER_BOUND,
    score_variant_mode: str = "PROBABILISTIC_ONLY",
    partial_credit_factor: float = REFERENCE_PARTIAL_CREDIT_FACTOR,
    **overrides,
) -> Dict[str, Any]:
    """An admissible tuning generation using the reference weight family."""
    payload: Dict[str, Any] = {
        "config_label": config_label,
        "auto_link_threshold": auto_link_threshold,
        "review_lower_bound": review_lower_bound,
        "score_variant_mode": score_variant_mode,
        "partial_credit_factor": partial_credit_factor,
    }
    payload.update(REFERENCE_WEIGHTS)
    return _merge(payload, overrides)


# ----------------------------------------------------------------------
# Patient records
# ----------------------------------------------------------------------

def patient_record_payload(
    source_mrn: str = "MRN-0001",
    given_name: str = "Maria",
    family_name: str = "Alvarez",
    birth_date: str = "1979-03-14",
    sex: str = "F",
    ssn_last4: Any = "4417",
    postal_code: Any = "94107",
    phone_digits: Any = "4155550142",
    sensitive_categories: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """A fully populated record: completeness score 6 over the six counted fields."""
    payload: Dict[str, Any] = {
        "source_mrn": source_mrn,
        "given_name": given_name,
        "family_name": family_name,
        "birth_date": birth_date,
        "sex": sex,
        "ssn_last4": ssn_last4,
        "postal_code": postal_code,
        "phone_digits": phone_digits,
    }
    if sensitive_categories is not None:
        payload["sensitive_categories"] = sensitive_categories
    return _merge(payload, overrides)


# ----------------------------------------------------------------------
# Consent directives
# ----------------------------------------------------------------------

def consent_directive_payload(
    directive_type: str = "OPT_OUT",
    scope: str = "ALL_PARTICIPANTS",
    expected_cluster_version: int = 1,
    restricted_categories: Optional[List[str]] = None,
    scoped_participant_id: Any = None,
    effective_from: Any = None,
    **overrides,
) -> Dict[str, Any]:
    """A cluster-wide opt-out directive; optional fields are omitted unless supplied."""
    payload: Dict[str, Any] = {
        "directive_type": directive_type,
        "scope": scope,
        "expected_cluster_version": expected_cluster_version,
    }
    if restricted_categories is not None:
        payload["restricted_categories"] = restricted_categories
    if scoped_participant_id is not None:
        payload["scoped_participant_id"] = scoped_participant_id
    if effective_from is not None:
        payload["effective_from"] = effective_from
    return _merge(payload, overrides)


# ----------------------------------------------------------------------
# Record locator queries
# ----------------------------------------------------------------------

def locator_query_payload(
    querying_participant_id: str,
    purpose_of_use: str = "TREATMENT",
    family_name: str = "Alvarez",
    given_name: str = "Maria",
    birth_date: str = "1979-03-14",
    sex: Any = "F",
    ssn_last4: Any = "4417",
    postal_code: Any = "94107",
    phone_digits: Any = "4155550142",
    break_glass_id: Any = None,
    **overrides,
) -> Dict[str, Any]:
    """Demographics identical to the reference record, so the match is exact."""
    payload: Dict[str, Any] = {
        "querying_participant_id": querying_participant_id,
        "purpose_of_use": purpose_of_use,
        "family_name": family_name,
        "given_name": given_name,
        "birth_date": birth_date,
    }
    for key, value in (
        ("sex", sex),
        ("ssn_last4", ssn_last4),
        ("postal_code", postal_code),
        ("phone_digits", phone_digits),
        ("break_glass_id", break_glass_id),
    ):
        if value is not None:
            payload[key] = value
    return _merge(payload, overrides)


# ----------------------------------------------------------------------
# Break-the-glass
# ----------------------------------------------------------------------

VALID_JUSTIFICATION = (
    "Unconscious trauma patient in the emergency department requires immediate history"
)
"""81 characters, comfortably past the forty-character minimum."""

EXACTLY_FORTY_CHAR_JUSTIFICATION = "Patient unresponsive; records needed now"
"""Exactly forty characters, which the PRD accepts at the boundary."""

THIRTY_NINE_CHAR_JUSTIFICATION = "Patient unresponsive; records needed no"
"""Thirty-nine characters, one short of the minimum."""


def break_glass_payload(
    cluster_id: str,
    invoking_participant_id: str,
    emergency_category: str = "UNCONSCIOUS_PATIENT",
    justification_text: str = VALID_JUSTIFICATION,
    **overrides,
) -> Dict[str, Any]:
    """An openable emergency session over one identity cluster."""
    return _merge(
        {
            "cluster_id": cluster_id,
            "invoking_participant_id": invoking_participant_id,
            "emergency_category": emergency_category,
            "justification_text": justification_text,
        },
        overrides,
    )


VALID_REVIEW_NOTE = (
    "Reviewed the emergency assertion against the chart and found no clinical basis"
)
"""78 characters, satisfying the forty-character minimum an UNJUSTIFIED note carries."""


# ----------------------------------------------------------------------
# Data feeds and quality samples
# ----------------------------------------------------------------------

def quality_sample_payload(
    period_start: str = "2026-07-01T00:00:00Z",
    period_end: str = "2026-07-08T00:00:00Z",
    messages_received: int = 10000,
    messages_rejected: int = 100,
    required_fields_missing_count: int = 50,
    duplicate_count: int = 25,
    timeliness_p95_seconds: int = 240,
    **overrides,
) -> Dict[str, Any]:
    """A clean window: reject rate 0.0100, well inside the degradation boundary."""
    return _merge(
        {
            "period_start": period_start,
            "period_end": period_end,
            "messages_received": messages_received,
            "messages_rejected": messages_rejected,
            "required_fields_missing_count": required_fields_missing_count,
            "duplicate_count": duplicate_count,
            "timeliness_p95_seconds": timeliness_p95_seconds,
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Notification subscriptions
# ----------------------------------------------------------------------

def subscription_payload(
    subscription_scope: str = "PATIENT_PANEL",
    event_types: Optional[List[str]] = None,
    delivery_endpoint_url: str = "https://alerts.altomesa.example/adt",
    cluster_id: Any = None,
    **overrides,
) -> Dict[str, Any]:
    """A panel-scoped subscription; `cluster_id` is omitted unless the scope needs it."""
    payload: Dict[str, Any] = {
        "subscription_scope": subscription_scope,
        "event_types": ["ADMISSION", "DISCHARGE"] if event_types is None else event_types,
        "delivery_endpoint_url": delivery_endpoint_url,
    }
    if cluster_id is not None:
        payload["cluster_id"] = cluster_id
    return _merge(payload, overrides)


# ----------------------------------------------------------------------
# Participation invoices
# ----------------------------------------------------------------------

def invoice_payload(
    billing_period_start: str = "2026-07-01T00:00:00Z",
    billing_period_end: str = "2026-08-01T00:00:00Z",
    basis_variant: str = "PROVISIONAL",
    due_date: str = "2026-09-01T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    """A fully elapsed July period as measured against the default clock."""
    return _merge(
        {
            "billing_period_start": billing_period_start,
            "billing_period_end": billing_period_end,
            "basis_variant": basis_variant,
            "due_date": due_date,
        },
        overrides,
    )
