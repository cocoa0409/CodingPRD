"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema PRD declares for the
request body. Only PRD-declared input fields are produced; computed and
system-managed fields are intentionally omitted so the implementation
cannot accidentally accept them as inputs.

PRD §2.4: timestamps are ISO 8601 UTC strings with three fractional
digits.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.4 format with three fractional digits.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp back into a timezone-aware
    datetime."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def iso_date(d: date) -> str:
    """ISO 8601 calendar date (YYYY-MM-DD)."""
    return d.isoformat()


def parse_anchor() -> datetime:
    """Convenience: the clock anchor as a datetime."""
    return parse_iso(TEST_DEFAULTS["CLOCK_ANCHOR"])


def iso_anchor_offset(*, days: int = 0, hours: int = 0,
                      minutes: int = 0, seconds: int = 0) -> str:
    """ISO 8601 UTC, offset from the clock anchor in
    TEST_DEFAULTS["CLOCK_ANCHOR"]."""
    return iso_utc(
        parse_anchor() + timedelta(
            days=days, hours=hours, minutes=minutes, seconds=seconds,
        ),
    )


# ---------------------------------------------------------------------------
# Random utilities.
# ---------------------------------------------------------------------------
_ALPHA_UPPER = string.ascii_uppercase
_ALPHANUM_UPPER = string.ascii_uppercase + string.digits
_DIGITS = string.digits


def random_suffix(n: int = 6) -> str:
    return "".join(random.choices(_ALPHANUM_UPPER, k=n))


def random_protocol_code() -> str:
    """PRD §3.1: "a 2–4 letter prefix, a hyphen, and 3–5 digits,
    matching the regex `^[A-Z]{2,4}-[0-9]{3,5}$`, unique across the
    system after trimming surrounding whitespace"."""
    prefix = "".join(random.choices(_ALPHA_UPPER, k=random.randint(2, 4)))
    suffix = "".join(random.choices(_DIGITS, k=random.randint(3, 5)))
    return f"{prefix}-{suffix}"


def random_arm_code() -> str:
    """PRD §3.1: "a short code of 1–8 uppercase alphanumeric characters
    (regex `^[A-Z0-9]{1,8}$`) that must be unique within the parent
    trial"."""
    return "".join(random.choices(_ALPHANUM_UPPER, k=random.randint(2, 6)))


def random_uri() -> str:
    """An opaque consent-document URI per PRD §3.1."""
    return f"s3://consents/{random_suffix(10)}.pdf"


# ---------------------------------------------------------------------------
# Trial — PRD §3.1 / §4.
# ---------------------------------------------------------------------------
DEFAULT_INCLUSION_CRITERIA: List[Dict[str, Any]] = [
    {"code": "AGE_GTE_18", "op": "GTE", "field": "age", "value": 18},
    {"code": "AGE_LTE_65", "op": "LTE", "field": "age", "value": 65},
]


DEFAULT_EXCLUSION_CRITERIA: List[Dict[str, Any]] = []


def create_trial_payload(
    *,
    protocol_code: Optional[str] = None,
    title: Optional[str] = None,
    sponsor_org: Optional[str] = None,
    inclusion_criteria: Optional[List[Dict[str, Any]]] = None,
    exclusion_criteria: Optional[List[Dict[str, Any]]] = None,
    randomization_scheme: str = "SIMPLE_BERNOULLI",
    block_size: Optional[int] = None,
    stratification_field: Optional[str] = None,
    target_enrollment: int = 10,
    blood_draw_window_days: int = 7,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /trials — PrincipalInvestigator only.

    PRD §3.1: required input fields are protocol_code (regex
    ^[A-Z]{2,4}-[0-9]{3,5}$, unique after trimming), title (1..200),
    sponsor_org, inclusion_criteria (<= 20 items), exclusion_criteria
    (<= 20 items), randomization_scheme (SIMPLE_BERNOULLI | PERMUTED_BLOCK
    | STRATIFIED_BLOCK), target_enrollment (1..10000), and
    blood_draw_window_days (0..14). block_size is required only when the
    scheme is PERMUTED_BLOCK or STRATIFIED_BLOCK; stratification_field is
    required only when the scheme is STRATIFIED_BLOCK.
    """
    payload: Dict[str, Any] = {
        "protocol_code": (
            protocol_code if protocol_code is not None
            else random_protocol_code()
        ),
        "title": (
            title if title is not None
            else f"Test Trial {random_suffix(4)}"
        ),
        "sponsor_org": (
            sponsor_org if sponsor_org is not None
            else "Acme Pharma"
        ),
        "inclusion_criteria": (
            list(inclusion_criteria)
            if inclusion_criteria is not None
            else list(DEFAULT_INCLUSION_CRITERIA)
        ),
        "exclusion_criteria": (
            list(exclusion_criteria)
            if exclusion_criteria is not None
            else list(DEFAULT_EXCLUSION_CRITERIA)
        ),
        "randomization_scheme": randomization_scheme,
        "target_enrollment": target_enrollment,
        "blood_draw_window_days": blood_draw_window_days,
    }
    # PRD §3.1: "When the scheme is PERMUTED_BLOCK or STRATIFIED_BLOCK
    # the payload also carries block_size, which must be one of 2, 4, 6,
    # or 8; for SIMPLE_BERNOULLI it must be null." We include the key
    # explicitly so PRD's "must be null" can be respected.
    if randomization_scheme == "SIMPLE_BERNOULLI":
        payload["block_size"] = None
    else:
        payload["block_size"] = block_size if block_size is not None else 4
    # PRD §3.1: "STRATIFIED_BLOCK additionally requires a non-null
    # stratification_field naming the profile attribute used to compute
    # strata."
    if stratification_field is not None:
        payload["stratification_field"] = stratification_field
    elif randomization_scheme == "STRATIFIED_BLOCK":
        payload["stratification_field"] = "stratum"
    payload.update(overrides)
    return payload


def patch_trial_payload(
    *,
    title: Optional[str] = None,
    sponsor_org: Optional[str] = None,
    inclusion_criteria: Optional[List[Dict[str, Any]]] = None,
    exclusion_criteria: Optional[List[Dict[str, Any]]] = None,
    target_enrollment: Optional[int] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /trials/{trial_id} — PrincipalInvestigator only.

    PRD §3.1: "While the trial is in DRAFT, the investigator can edit
    title, sponsor_org, inclusion_criteria, exclusion_criteria, and
    target_enrollment through the metadata-update endpoint; that
    endpoint also accepts an optional version to drive OCC."
    """
    payload: Dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if sponsor_org is not None:
        payload["sponsor_org"] = sponsor_org
    if inclusion_criteria is not None:
        payload["inclusion_criteria"] = list(inclusion_criteria)
    if exclusion_criteria is not None:
        payload["exclusion_criteria"] = list(exclusion_criteria)
    if target_enrollment is not None:
        payload["target_enrollment"] = target_enrollment
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Arm — PRD §3.1 / §4.
# ---------------------------------------------------------------------------
def create_arm_payload(
    *,
    code: Optional[str] = None,
    label: Optional[str] = None,
    weight: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /trials/{trial_id}/arms — PrincipalInvestigator only.

    PRD §3.1: "Each arm carries a short code of 1–8 uppercase
    alphanumeric characters (regex `^[A-Z0-9]{1,8}$`) that must be
    unique within the parent trial, a human-readable label, and a
    weight integer between 1 and 10 inclusive."
    """
    payload: Dict[str, Any] = {
        "code": code if code is not None else random_arm_code(),
        "label": (
            label if label is not None
            else f"Arm {random_suffix(3)}"
        ),
        "weight": weight,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Consent versions — PRD §2.10 / §3.1 / §4.
# ---------------------------------------------------------------------------
def create_consent_version_payload(
    *,
    document_uri: Optional[str] = None,
    change_summary: Optional[str] = None,
    requires_re_consent: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /trials/{trial_id}/consent-versions — PrincipalInvestigator
    only.

    PRD §2.10: "Publishing a second or later version requires
    change_summary of between 1 and 500 characters; publishing the first
    version does not require change_summary." The factory omits
    change_summary unless the caller supplies one — appropriate for v1
    publishes and explicit overrides for v2+.

    PRD §2.10: "The requires_re_consent flag on a ConsentVersion is a
    publish-time boolean".
    """
    payload: Dict[str, Any] = {
        "document_uri": (
            document_uri if document_uri is not None else random_uri()
        ),
    }
    if change_summary is not None:
        payload["change_summary"] = change_summary
    if requires_re_consent is not None:
        payload["requires_re_consent"] = requires_re_consent
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# IRB review — PRD §3.2 / §4.
# ---------------------------------------------------------------------------
def create_irb_review_payload(
    *,
    decision: str = "APPROVED",
    notes: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /trials/{trial_id}/irb-reviews — IRBReviewer only.

    PRD §3.2: "decision value of APPROVED, REVISIONS_REQUESTED, or
    REJECTED, plus reviewer notes of 1 to 1000 characters."
    """
    payload: Dict[str, Any] = {
        "decision": decision,
        "notes": (
            notes if notes is not None
            else f"Decision rationale {random_suffix(4)}"
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Participants — PRD §3.4 / §4.
# ---------------------------------------------------------------------------
DEFAULT_PROFILE: Dict[str, Any] = {"age": 30}


def create_participant_payload(
    *,
    trial_id: str,
    profile: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /participants — StudyCoordinator only.

    PRD §3.4: "A StudyCoordinator creates a participant in the SCREENING
    state by attaching them to a trial via trial_id and supplying their
    profile — a bag of typed attribute keys (at most 50 keys, scalar
    values) that will be evaluated against the trial's inclusion and
    exclusion criteria."
    """
    payload: Dict[str, Any] = {
        "trial_id": trial_id,
        "profile": (
            dict(profile) if profile is not None else dict(DEFAULT_PROFILE)
        ),
    }
    payload.update(overrides)
    return payload


def sign_consent_payload(
    *,
    consent_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /participants/{participant_id}/sign-consent —
    Participant_self or StudyCoordinator.

    PRD §3.5: "the participant (or, on their behalf, the coordinator)
    signs consent by submitting a consent_version integer in the body."
    """
    payload: Dict[str, Any] = {"consent_version": consent_version}
    payload.update(overrides)
    return payload


def withdraw_participant_payload(
    *,
    reason: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /participants/{participant_id}/withdraw.

    PRD §3.7: "the coordinator or the participant themselves submits the
    withdraw action with an optional reason".
    """
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Visits — PRD §3.6 / §4.
# ---------------------------------------------------------------------------
def create_visit_payload(
    *,
    sequence_no: int = 1,
    target_date: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /participants/{participant_id}/visits — StudyCoordinator.

    PRD §3.6: "Each visit creation carries a 1-indexed sequence_no
    between 1 and 50 that must be unique within the participant (any
    duplicate is ERR_DUPLICATE_VISIT_SEQUENCE), plus a target_date for
    the protocol-scheduled blood draw."
    """
    payload: Dict[str, Any] = {
        "sequence_no": sequence_no,
        "target_date": (
            target_date if target_date is not None
            else iso_anchor_offset(days=10)
        ),
    }
    payload.update(overrides)
    return payload


def complete_visit_payload(
    *,
    actual_draw_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /visits/{visit_id}/complete — StudyCoordinator.

    PRD §3.6: "the coordinator submits the visit-complete request with
    actual_draw_at."
    """
    payload: Dict[str, Any] = {"actual_draw_at": actual_draw_at}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Adverse events — PRD §3.7 / §4.
# ---------------------------------------------------------------------------
def create_adverse_event_payload(
    *,
    severity: str = "MILD",
    narrative: Optional[str] = None,
    caused_visit_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /participants/{participant_id}/adverse-events.

    PRD §3.7: "A StudyCoordinator or a PrincipalInvestigator records an
    adverse event against a participant by submitting severity, a
    narrative of 1 to 2000 characters, and an optional caused_visit_id
    pointing at a visit on the same participant."
    """
    payload: Dict[str, Any] = {
        "severity": severity,
        "narrative": (
            narrative if narrative is not None
            else f"AE narrative {random_suffix(4)}"
        ),
    }
    if caused_visit_id is not None:
        payload["caused_visit_id"] = caused_visit_id
    payload.update(overrides)
    return payload


def resolve_adverse_event_payload(
    *,
    resolution_note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /participants/{participant_id}/adverse-events/{adverse_event_id}
    /resolve — PrincipalInvestigator.

    PRD §3.7: "the investigator may resolve the event from UNDER_REVIEW
    by supplying a resolution_note of 1 to 1000 characters".
    """
    payload: Dict[str, Any] = {
        "resolution_note": (
            resolution_note if resolution_note is not None
            else f"Resolved {random_suffix(4)}"
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Trial terminate — PRD §3.3 / §4.
# ---------------------------------------------------------------------------
def terminate_trial_payload(
    *,
    reason: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /trials/{trial_id}/terminate — PrincipalInvestigator.

    PRD §3.3: "the investigator may terminate the trial outright,
    optionally supplying a reason field".
    """
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance — PRD §2.12 / §4.
# ---------------------------------------------------------------------------
def clock_advance_payload(
    *,
    to_iso8601: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /_clock/advance — admin-only test-driving capability.

    PRD §2.12: "an admin-only test-driving capability advances the
    logical clock to a supplied to_iso8601 instant. The submitted
    timestamp must be greater than or equal to the current clock; the
    clock is monotonic and may not be moved backwards."
    """
    payload: Dict[str, Any] = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


def occ_payload(version: Optional[int] = None,
                **overrides: Any) -> Dict[str, Any]:
    """Minimal action-payload that only carries an optional version for
    PRD §2.6 OCC checks. Many state-change actions accept this shape:
    nothing in the body except version."""
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


__all__ = [
    # time helpers
    "iso_utc",
    "parse_iso",
    "iso_date",
    "parse_anchor",
    "iso_anchor_offset",
    # random helpers
    "random_suffix",
    "random_protocol_code",
    "random_arm_code",
    "random_uri",
    # defaults
    "DEFAULT_INCLUSION_CRITERIA",
    "DEFAULT_EXCLUSION_CRITERIA",
    "DEFAULT_PROFILE",
    # payload factories
    "create_trial_payload",
    "patch_trial_payload",
    "create_arm_payload",
    "create_consent_version_payload",
    "create_irb_review_payload",
    "create_participant_payload",
    "sign_consent_payload",
    "withdraw_participant_payload",
    "create_visit_payload",
    "complete_visit_payload",
    "create_adverse_event_payload",
    "resolve_adverse_event_payload",
    "terminate_trial_payload",
    "clock_advance_payload",
    "occ_payload",
]
