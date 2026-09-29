"""Request-payload factories: input fields only, never server-derived fields.

Each factory returns a plain dict carrying sensible declared values that a test can
override by keyword. Decimal inputs are emitted as JSON numbers, never as strings.

A field whose value is :data:`OMIT` is left out of the payload entirely, which is how
a test distinguishes "omitted so the declared default applies" from "explicitly null".
"""

from typing import Any, Dict, List

from .constants import CLOCK_EPOCH
from .types import (
    ActionType,
    ActivityKind,
    CycleType,
    DeficiencyClass,
    DesignationLevel,
    Decision,
    EdDisposition,
    ResponderRole,
    RuleKind,
    RuleSeverity,
    TierCode,
    TriageReviewStatus,
)


class _Omit:
    """Sentinel marking a payload key that must not be sent at all."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


OMIT = _Omit()


def _compact(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop every key whose value is the OMIT sentinel."""
    return {k: v for k, v in payload.items() if not isinstance(v, _Omit)}


# ─── The logical clock ────────────────────────────────────


def clock_payload(to_iso8601: str = CLOCK_EPOCH, **overrides: Any) -> Dict[str, Any]:
    """Body for moving the logical clock."""
    payload: Dict[str, Any] = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return _compact(payload)


# ─── Trauma centers and tiers ─────────────────────────────


def trauma_center_payload(
    name: str = "Riverbend Trauma",
    state_code: str = "NE",
    designation_level: str = DesignationLevel.LEVEL_II,
    verification_cycle_start_date: str = "2026-01-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for registering a trauma center."""
    payload: Dict[str, Any] = {
        "name": name,
        "state_code": state_code,
        "designation_level": designation_level,
        "verification_cycle_start_date": verification_cycle_start_date,
    }
    payload.update(overrides)
    return _compact(payload)


def activation_tier_payload(
    tier_code: str = TierCode.TIER_1_FULL,
    surgeon_response_limit_minutes: int = 15,
    specialty_response_limit_minutes: int = 30,
    iss_threshold: int = 16,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for configuring one activation criteria tier."""
    payload: Dict[str, Any] = {
        "tier_code": tier_code,
        "surgeon_response_limit_minutes": surgeon_response_limit_minutes,
        "specialty_response_limit_minutes": specialty_response_limit_minutes,
        "iss_threshold": iss_threshold,
    }
    payload.update(overrides)
    return _compact(payload)


# ─── Data dictionary rules ────────────────────────────────


def data_dictionary_rule_payload(
    field_name: str = "gcs_arrival",
    rule_kind: str = RuleKind.RANGE,
    severity: str = RuleSeverity.MAJOR,
    min_value: Any = 3,
    max_value: Any = 15,
    allowed_codes: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for declaring one dictionary rule.

    A RANGE rule carries the inclusive bounds, a CONFORMANCE rule carries
    ``allowed_codes``, and a REQUIRED rule needs neither.
    """
    payload: Dict[str, Any] = {
        "field_name": field_name,
        "rule_kind": rule_kind,
        "severity": severity,
        "min_value": min_value,
        "max_value": max_value,
        "allowed_codes": allowed_codes,
    }
    payload.update(overrides)
    return _compact(payload)


def required_rule_payload(
    field_name: str, severity: str = RuleSeverity.MAJOR, **overrides: Any
) -> Dict[str, Any]:
    """Body for a REQUIRED rule, which needs neither bounds nor codes."""
    return data_dictionary_rule_payload(
        field_name=field_name,
        rule_kind=RuleKind.REQUIRED,
        severity=severity,
        min_value=OMIT,
        max_value=OMIT,
        allowed_codes=OMIT,
        **overrides,
    )


def range_rule_payload(
    field_name: str,
    min_value: int,
    max_value: int,
    severity: str = RuleSeverity.MAJOR,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for a RANGE rule with inclusive bounds."""
    return data_dictionary_rule_payload(
        field_name=field_name,
        rule_kind=RuleKind.RANGE,
        severity=severity,
        min_value=min_value,
        max_value=max_value,
        allowed_codes=OMIT,
        **overrides,
    )


def conformance_rule_payload(
    field_name: str,
    allowed_codes: List[str],
    severity: str = RuleSeverity.MAJOR,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for a CONFORMANCE rule carrying its permitted codes."""
    return data_dictionary_rule_payload(
        field_name=field_name,
        rule_kind=RuleKind.CONFORMANCE,
        severity=severity,
        min_value=OMIT,
        max_value=OMIT,
        allowed_codes=allowed_codes,
        **overrides,
    )


# ─── Registry cases ───────────────────────────────────────


def registry_case_payload(
    center_id: str,
    activation_tier_id: str,
    mrn: str = "MRN-0001",
    arrival_at: str = "2026-07-15T08:00:00Z",
    injury_severity_score: int = 22,
    los_hours: float = 96.00,
    ed_disposition: Any = EdDisposition.ADMIT,
    transfer_in_from_center_id: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for opening a registry case."""
    payload: Dict[str, Any] = {
        "center_id": center_id,
        "activation_tier_id": activation_tier_id,
        "mrn": mrn,
        "arrival_at": arrival_at,
        "injury_severity_score": injury_severity_score,
        "los_hours": los_hours,
        "ed_disposition": ed_disposition,
        "transfer_in_from_center_id": transfer_in_from_center_id,
    }
    payload.update(overrides)
    return _compact(payload)


def triage_review_payload(
    triage_review_status: str = TriageReviewStatus.APPROPRIATE,
    review_note: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for adjudicating a case's triage decision."""
    payload: Dict[str, Any] = {
        "triage_review_status": triage_review_status,
        "review_note": review_note,
    }
    payload.update(overrides)
    return _compact(payload)


def transfer_out_payload(
    transfer_out_to_center_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Body for recording a transfer-out."""
    payload: Dict[str, Any] = {
        "transfer_out_to_center_id": transfer_out_to_center_id
    }
    payload.update(overrides)
    return _compact(payload)


def rescind_transfer_out_payload(
    rescind_reason: str = "Receiving center refused the patient; the transfer never occurred.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for rescinding a recorded transfer-out."""
    payload: Dict[str, Any] = {"rescind_reason": rescind_reason}
    payload.update(overrides)
    return _compact(payload)


# ─── Abstraction records ──────────────────────────────────


def abstraction_payload(
    expected_case_version: Any,
    iss_abstracted: Any = 22,
    gcs_arrival: Any = 12,
    mechanism_code: Any = "FALL",
    ed_departure_at: Any = "2026-07-15T11:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for submitting an abstraction against a case.

    All four abstracted values are nullable on the wire, so passing ``None`` sends an
    explicit null while passing :data:`OMIT` leaves the key out.
    """
    payload: Dict[str, Any] = {
        "expected_case_version": expected_case_version,
        "iss_abstracted": iss_abstracted,
        "gcs_arrival": gcs_arrival,
        "mechanism_code": mechanism_code,
        "ed_departure_at": ed_departure_at,
    }
    payload.update(overrides)
    return _compact(payload)


def reject_abstraction_payload(
    rejection_reason: str = "Abstracted severity disagrees with the source chart.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for rejecting a submitted abstraction."""
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return _compact(payload)


# ─── Response logs ────────────────────────────────────────


def response_log_payload(
    responder_role: str = ResponderRole.SURGEON,
    responder_user_id: str = "u_surgeon_1",
    notified_at: str = "2026-07-15T08:00:00Z",
    arrived_at: Any = "2026-07-15T08:12:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for documenting one responder's notification and arrival."""
    payload: Dict[str, Any] = {
        "responder_role": responder_role,
        "responder_user_id": responder_user_id,
        "notified_at": notified_at,
        "arrived_at": arrived_at,
    }
    payload.update(overrides)
    return _compact(payload)


# ─── PI events and corrective actions ─────────────────────


def pi_event_payload(
    center_id: str,
    event_type: str = "TRANSFER_DELAY",
    severity: str = "MEDIUM",
    case_id: Any = OMIT,
    source_deficiency_id: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for opening a PI event manually."""
    payload: Dict[str, Any] = {
        "center_id": center_id,
        "event_type": event_type,
        "severity": severity,
        "case_id": case_id,
        "source_deficiency_id": source_deficiency_id,
    }
    payload.update(overrides)
    return _compact(payload)


def corrective_action_payload(
    action_type: str = ActionType.EDUCATION,
    owner_user_id: str = "u_owner_1",
    due_at: str = "2026-09-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for attaching a corrective action to an event under review."""
    payload: Dict[str, Any] = {
        "action_type": action_type,
        "owner_user_id": owner_user_id,
        "due_at": due_at,
    }
    payload.update(overrides)
    return _compact(payload)


def complete_action_payload(
    completion_note: Any = "Corrective action delivered and documented.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for recording completion of a corrective action."""
    payload: Dict[str, Any] = {"completion_note": completion_note}
    payload.update(overrides)
    return _compact(payload)


def close_loop_payload(
    loop_closure_note: str = "Loop closed: every corrective action verified.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for documenting loop closure."""
    payload: Dict[str, Any] = {"loop_closure_note": loop_closure_note}
    payload.update(overrides)
    return _compact(payload)


def reopen_payload(
    reopen_reason: str = "Recurrence found in the following month's audit.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for reopening a closed loop."""
    payload: Dict[str, Any] = {"reopen_reason": reopen_reason}
    payload.update(overrides)
    return _compact(payload)


# ─── Verification cycles ──────────────────────────────────


def verification_cycle_payload(
    center_id: str,
    cycle_type: str = CycleType.NATIONAL_VERIFICATION,
    site_visit_date: str = "2026-10-15T13:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for opening a verification cycle."""
    payload: Dict[str, Any] = {
        "center_id": center_id,
        "cycle_type": cycle_type,
        "site_visit_date": site_visit_date,
    }
    payload.update(overrides)
    return _compact(payload)


def schedule_site_visit_payload(
    site_visit_date: str = "2026-10-15T13:00:00Z", **overrides: Any
) -> Dict[str, Any]:
    """Body for confirming the site visit date of a submitted cycle."""
    payload: Dict[str, Any] = {"site_visit_date": site_visit_date}
    payload.update(overrides)
    return _compact(payload)


def decide_payload(
    decision: str = Decision.VERIFIED,
    decision_effective_date: str = "2026-11-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for rendering a cycle decision."""
    payload: Dict[str, Any] = {
        "decision": decision,
        "decision_effective_date": decision_effective_date,
    }
    payload.update(overrides)
    return _compact(payload)


# ─── Criteria deficiencies ────────────────────────────────


def criteria_deficiency_payload(
    criterion_code: str = "CD-05-13",
    deficiency_class: str = DeficiencyClass.TYPE_II_MAJOR,
    remediation_due_at: str = "2026-09-30T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for recording a criteria deficiency on a cycle."""
    payload: Dict[str, Any] = {
        "criterion_code": criterion_code,
        "deficiency_class": deficiency_class,
        "remediation_due_at": remediation_due_at,
    }
    payload.update(overrides)
    return _compact(payload)


def remediation_payload(
    expected_cycle_version: Any,
    remediation_note: str = "Remediation evidence attached for reviewer acceptance.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for submitting a remediation packet."""
    payload: Dict[str, Any] = {
        "expected_cycle_version": expected_cycle_version,
        "remediation_note": remediation_note,
    }
    payload.update(overrides)
    return _compact(payload)


def escalate_payload(
    escalation_reason: str = "Remediation evidence did not arrive before the deadline.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for escalating an unremediated deficiency."""
    payload: Dict[str, Any] = {"escalation_reason": escalation_reason}
    payload.update(overrides)
    return _compact(payload)


# ─── Surveyor bookings ────────────────────────────────────


def surveyor_booking_payload(
    surveyor_user_id: str = "u_surveyor_1",
    window_start: str = "2026-09-10T08:00:00Z",
    window_end: str = "2026-09-10T17:00:00Z",
    travel_buffer_hours: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for booking a surveyor review window."""
    payload: Dict[str, Any] = {
        "surveyor_user_id": surveyor_user_id,
        "window_start": window_start,
        "window_end": window_end,
        "travel_buffer_hours": travel_buffer_hours,
    }
    payload.update(overrides)
    return _compact(payload)


# ─── Outreach activities ──────────────────────────────────


def outreach_activity_payload(
    activity_kind: str = ActivityKind.INJURY_PREVENTION,
    event_date: str = "2026-06-14T00:00:00Z",
    credit_hours: float = 1.15,
    audience_count: int = 60,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for logging one outreach activity."""
    payload: Dict[str, Any] = {
        "activity_kind": activity_kind,
        "event_date": event_date,
        "credit_hours": credit_hours,
        "audience_count": audience_count,
    }
    payload.update(overrides)
    return _compact(payload)


def reject_outreach_payload(
    rejection_reason: str = "Attendance roster could not be produced for audit.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for rejecting a logged or verified outreach activity."""
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return _compact(payload)


# ─── Referral agreements ──────────────────────────────────


def referral_agreement_payload(
    referring_center_id: str,
    receiving_center_id: str,
    effective_from: str = "2026-01-01T00:00:00Z",
    effective_to: str = "2027-01-01T00:00:00Z",
    guaranteed_acceptance_minutes: int = 30,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for drafting a referral agreement on a directed center pair."""
    payload: Dict[str, Any] = {
        "referring_center_id": referring_center_id,
        "receiving_center_id": receiving_center_id,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "guaranteed_acceptance_minutes": guaranteed_acceptance_minutes,
    }
    payload.update(overrides)
    return _compact(payload)


def terminate_agreement_payload(
    termination_reason: str = "Coverage renegotiated onto a fresh agreement.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for terminating an active agreement."""
    payload: Dict[str, Any] = {"termination_reason": termination_reason}
    payload.update(overrides)
    return _compact(payload)
