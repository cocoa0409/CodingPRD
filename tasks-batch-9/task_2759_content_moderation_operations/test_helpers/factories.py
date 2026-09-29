"""Payload factories: valid-by-default request bodies with keyword overrides.

Every factory returns a body that the API accepts as-is, so a test states only
the one field its claim turns on. Numeric inputs are emitted as JSON numbers,
never as strings, because the API declares confidences and thresholds as
decimal fractions and counts as integers.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    CLOCK_T0,
    DEFAULT_APPEAL_WINDOW_HOURS,
    DEFAULT_REVIEW_SLA_MINUTES,
)

# ---------------------------------------------------------------------------
# Default field values, one block per request body
# ---------------------------------------------------------------------------

DEFAULTS: Dict[str, Dict[str, Any]] = {
    "account": {
        "external_handle": "acct_1",
        "region_code": "US",
        "tier": "STANDARD",
    },
    "content_item": {
        "language": "EN",
        "media_kind": "TEXT",
        "graphic_weight": 2,
    },
    "policy_category": {
        "code": "VIOLENT_THREAT",
        "name": "Violent Threat",
        "severity_tier": "T2",
        "specialty": "VIOLENCE",
    },
    "policy_version": {
        "version_label": "v1",
        "auto_action_threshold": 0.9,
        "review_floor": 0.4,
        "enforcement_action": "REMOVE",
        "appeal_window_hours": DEFAULT_APPEAL_WINDOW_HOURS,
        "review_sla_minutes": DEFAULT_REVIEW_SLA_MINUTES,
    },
    "policy_version_revision": {
        "auto_action_threshold": 0.9,
        "review_floor": 0.4,
    },
    "review_queue": {
        "name": "EN Violence",
        "language": "EN",
        "specialty": "VIOLENCE",
    },
    "reviewer": {
        "display_name": "Rita Reviewer",
        "languages": ["EN"],
        "specialties": ["VIOLENCE"],
        "role_class": "FRONTLINE",
        "utc_offset_minutes": 0,
        "shift_start_local_hour": 8,
        "shift_end_local_hour": 20,
    },
    "detection_signal": {
        "policy_category_code": "VIOLENT_THREAT",
        "classifier_id": "clf-violence-1",
        "classifier_confidence": 0.7,
    },
    "moderation_case": {
        "policy_category_code": "VIOLENT_THREAT",
        "origin": "MANUAL_REPORT",
    },
    "case_assignment": {},
    "case_decision": {
        "outcome": "REMOVE",
        "rationale": "Clear policy breach.",
    },
    "case_escalation": {
        "escalation_reason": "CALIBRATION",
    },
    "case_return": {
        "reason": "Needs a frontline second look.",
    },
    "certification": {},
    "wellness_break": {
        "break_minutes": 60,
        "reason": "Rotation rest.",
    },
    "appeal": {
        "grounds_text": "The content was satire and breached no policy.",
    },
    "appeal_routing": {},
    "appeal_resolution": {
        "resolution": "UPHELD",
        "resolution_note": "Original call stands.",
    },
    "audit_sample": {
        "sampling_reason": "RANDOM",
    },
    "audit_verdict": {
        "verdict": "AGREE",
    },
    "audit_dispute": {
        "dispute_note": "The verdict misreads the policy text.",
    },
    "transparency_report": {
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-08-31T23:59:59Z",
    },
    "report_computation": {
        "variant": "PROVISIONAL",
    },
    "clock": {
        "to_iso8601": CLOCK_T0,
    },
}


def _build(kind: str, overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge overrides over the defaults for one body kind.

    A caller may delete an optional field entirely by overriding it with the
    ``OMIT`` sentinel, which is how the default-application tests exercise the
    server's own defaults.
    """
    payload = dict(DEFAULTS[kind])
    for key, value in overrides.items():
        if value is OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    """Sentinel telling a factory to leave an optional field out entirely."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


OMIT = _Omit()


# ---------------------------------------------------------------------------
# Resource creation bodies
# ---------------------------------------------------------------------------


def create_account_payload(**overrides: Any) -> Dict[str, Any]:
    """A registration body for an author brought under supervision."""
    return _build("account", overrides)


def create_content_item_payload(account_id: str, **overrides: Any) -> Dict[str, Any]:
    """An ingestion body for a piece of content authored by an account."""
    payload = _build("content_item", overrides)
    payload.setdefault("account_id", account_id)
    if "account_id" in overrides:
        payload["account_id"] = overrides["account_id"]
    return payload


def create_policy_category_payload(**overrides: Any) -> Dict[str, Any]:
    """A taxonomy node body."""
    return _build("policy_category", overrides)


def create_policy_version_payload(policy_category_id: str, **overrides: Any) -> Dict[str, Any]:
    """A draft enforcement-rule body beneath a category."""
    payload = _build("policy_version", overrides)
    payload.setdefault("policy_category_id", policy_category_id)
    if "policy_category_id" in overrides:
        payload["policy_category_id"] = overrides["policy_category_id"]
    return payload


def revise_policy_version_payload(**overrides: Any) -> Dict[str, Any]:
    """A revision body that overwrites the routing thresholds."""
    return _build("policy_version_revision", overrides)


def create_review_queue_payload(policy_category_id: str, **overrides: Any) -> Dict[str, Any]:
    """A queue body serving one category in one language."""
    payload = _build("review_queue", overrides)
    payload.setdefault("policy_category_id", policy_category_id)
    if "policy_category_id" in overrides:
        payload["policy_category_id"] = overrides["policy_category_id"]
    return payload


def create_reviewer_payload(**overrides: Any) -> Dict[str, Any]:
    """An onboarding body for a reviewer with a full-day shift."""
    return _build("reviewer", overrides)


def create_detection_signal_payload(content_item_id: str, **overrides: Any) -> Dict[str, Any]:
    """A classifier submission body against one content item."""
    payload = _build("detection_signal", overrides)
    payload.setdefault("content_item_id", content_item_id)
    if "content_item_id" in overrides:
        payload["content_item_id"] = overrides["content_item_id"]
    return payload


def create_moderation_case_payload(content_item_id: str, **overrides: Any) -> Dict[str, Any]:
    """A hand-opened case body; the default origin is a manual report."""
    payload = _build("moderation_case", overrides)
    payload.setdefault("content_item_id", content_item_id)
    if "content_item_id" in overrides:
        payload["content_item_id"] = overrides["content_item_id"]
    return payload


def legal_case_payload(content_item_id: str, **overrides: Any) -> Dict[str, Any]:
    """A legal-request case body carrying its jurisdiction and reference."""
    defaults = {
        "origin": "LEGAL_REQUEST",
        "legal_jurisdiction": "DE",
        "legal_reference": "LG-BERLIN-2026-114",
    }
    defaults.update(overrides)
    return create_moderation_case_payload(content_item_id, **defaults)


# ---------------------------------------------------------------------------
# Workflow action bodies
# ---------------------------------------------------------------------------


def assign_case_payload(
    expected_case_version: int,
    target_reviewer_id: Optional[str] = None,
    exclude_reviewer_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """An assignment body; the version expectation is a required input."""
    payload: Dict[str, Any] = {"expected_case_version": expected_case_version}
    if target_reviewer_id is not None:
        payload["target_reviewer_id"] = target_reviewer_id
    if exclude_reviewer_ids is not None:
        payload["exclude_reviewer_ids"] = exclude_reviewer_ids
    for key, value in overrides.items():
        if value is OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def decide_case_payload(**overrides: Any) -> Dict[str, Any]:
    """A decision body carrying the recorded outcome."""
    return _build("case_decision", overrides)


def escalate_case_payload(**overrides: Any) -> Dict[str, Any]:
    """An escalation body carrying the supplied reason."""
    return _build("case_escalation", overrides)


def return_case_payload(**overrides: Any) -> Dict[str, Any]:
    """A return-to-queue body with an optional recorded reason."""
    return _build("case_return", overrides)


def certification_payload(policy_version_id: str, expected_reviewer_version: int, **overrides: Any) -> Dict[str, Any]:
    """A certification grant body; the version expectation is a required input."""
    payload: Dict[str, Any] = {
        "policy_version_id": policy_version_id,
        "expected_reviewer_version": expected_reviewer_version,
    }
    for key, value in overrides.items():
        if value is OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def wellness_break_payload(**overrides: Any) -> Dict[str, Any]:
    """A protective-break body carrying its length in minutes."""
    return _build("wellness_break", overrides)


def create_appeal_payload(case_id: str, **overrides: Any) -> Dict[str, Any]:
    """An appeal body naming the contested case and stating its grounds."""
    payload = _build("appeal", overrides)
    payload.setdefault("case_id", case_id)
    if "case_id" in overrides:
        payload["case_id"] = overrides["case_id"]
    return payload


def route_appeal_payload(target_reviewer_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    """A routing body that may name an independent reviewer or leave the choice open."""
    payload: Dict[str, Any] = {}
    if target_reviewer_id is not None:
        payload["target_reviewer_id"] = target_reviewer_id
    for key, value in overrides.items():
        if value is OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def resolve_appeal_payload(**overrides: Any) -> Dict[str, Any]:
    """A resolution body carrying the upheld or overturned outcome."""
    return _build("appeal_resolution", overrides)


def create_audit_sample_payload(case_id: str, **overrides: Any) -> Dict[str, Any]:
    """A sampling body naming the decided case being drawn."""
    payload = _build("audit_sample", overrides)
    payload.setdefault("case_id", case_id)
    if "case_id" in overrides:
        payload["case_id"] = overrides["case_id"]
    return payload


def audit_verdict_payload(**overrides: Any) -> Dict[str, Any]:
    """A verdict body; a disagreement must also name the correct outcome."""
    return _build("audit_verdict", overrides)


def audit_dispute_payload(**overrides: Any) -> Dict[str, Any]:
    """A dispute body carrying the deciding reviewer's note."""
    return _build("audit_dispute", overrides)


def create_transparency_report_payload(**overrides: Any) -> Dict[str, Any]:
    """A reporting-period body over a closed interval."""
    return _build("transparency_report", overrides)


def compute_report_payload(**overrides: Any) -> Dict[str, Any]:
    """A computation body naming the variant to compute under."""
    return _build("report_computation", overrides)


def clock_payload(**overrides: Any) -> Dict[str, Any]:
    """A clock body naming the instant to move to."""
    return _build("clock", overrides)
