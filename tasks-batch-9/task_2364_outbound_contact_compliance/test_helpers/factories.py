"""Request-payload factories.

Each factory returns only the *input* fields the PRD declares for its endpoint;
server-derived fields are never supplied. Keyword overrides replace defaults, and
passing ``None`` for an optional key omits it entirely so the server default is
exercised.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_ATTEMPT_BUDGET_TOTAL,
    PHONE_C1,
    STATE_CA,
    TZ_LOS_ANGELES,
    UTC_OFFSET_LOS_ANGELES,
)
from .types import (
    AllegedViolationType,
    AttemptOutcome,
    CampaignPurpose,
    CaptureMethod,
    Channel,
    ComplaintSource,
    ConsentType,
    DialerMode,
    DisclosureBlockType,
    ListType,
    Payload,
    PhoneType,
    RecordingConsentMode,
    RecordingConsentRegime,
    RemovalReason,
    RevocationChannelReceived,
    RevocationMethod,
    RevocationScope,
    SuppressionSource,
    VoidReason,
)


def _compact(payload: Dict[str, Any]) -> Payload:
    """Drop keys whose value is ``None`` so optional inputs stay absent."""
    return {k: v for k, v in payload.items() if v is not None}


# ---------------------------------------------------------------------------
# Contact
# ---------------------------------------------------------------------------


def contact_payload(
    phone_number: str = PHONE_C1,
    state_code: str = STATE_CA,
    utc_offset_minutes: int = UTC_OFFSET_LOS_ANGELES,
    time_zone_label: str = TZ_LOS_ANGELES,
    phone_type: Optional[str] = PhoneType.WIRELESS,
    attempt_budget_total: Optional[int] = DEFAULT_ATTEMPT_BUDGET_TOTAL,
    **overrides: Any,
) -> Payload:
    """Input for POST /compliance/contacts."""
    payload = {
        "phone_number": phone_number,
        "state_code": state_code,
        "utc_offset_minutes": utc_offset_minutes,
        "time_zone_label": time_zone_label,
        "phone_type": phone_type,
        "attempt_budget_total": attempt_budget_total,
    }
    payload.update(overrides)
    return _compact(payload)


def number_status_check_payload(
    claimed_consent_date: str = "2026-07-15", **overrides: Any
) -> Payload:
    """Input for POST /compliance/contacts/{id}/number-status-check."""
    payload = {"claimed_consent_date": claimed_consent_date}
    payload.update(overrides)
    return _compact(payload)


# ---------------------------------------------------------------------------
# ConsentRecord
# ---------------------------------------------------------------------------


def consent_record_payload(
    contact_id: str,
    disclosure_script_id: str,
    expected_contact_version: int,
    channel: str = Channel.VOICE,
    consent_type: str = ConsentType.EXPRESS_WRITTEN,
    capture_method: str = CaptureMethod.WEB_FORM,
    disclosure_text_version: int = 1,
    signature_evidence: str = "evidence-c1",
    **overrides: Any,
) -> Payload:
    """Input for POST /compliance/consent-records."""
    payload = {
        "contact_id": contact_id,
        "channel": channel,
        "consent_type": consent_type,
        "capture_method": capture_method,
        "disclosure_script_id": disclosure_script_id,
        "disclosure_text_version": disclosure_text_version,
        "signature_evidence": signature_evidence,
        "expected_contact_version": expected_contact_version,
    }
    payload.update(overrides)
    return _compact(payload)


def consent_suspend_payload(
    reason: str = "Evidence under audit", **overrides: Any
) -> Payload:
    """Input for POST /compliance/consent-records/{id}/suspend."""
    payload = {"reason": reason}
    payload.update(overrides)
    return _compact(payload)


def consent_reinstate_payload(
    reinstatement_note: str = "Evidence verified", **overrides: Any
) -> Payload:
    """Input for POST /compliance/consent-records/{id}/reinstate."""
    payload = {"reinstatement_note": reinstatement_note}
    payload.update(overrides)
    return _compact(payload)


# ---------------------------------------------------------------------------
# RevocationRequest
# ---------------------------------------------------------------------------


def revocation_request_payload(
    contact_id: str,
    channel_received: str = RevocationChannelReceived.SMS,
    method: str = RevocationMethod.REPLY_STOP,
    scope: str = RevocationScope.ALL_CHANNELS,
    received_note: str = "Consumer replied STOP",
    **overrides: Any,
) -> Payload:
    """Input for POST /compliance/revocation-requests."""
    payload = {
        "contact_id": contact_id,
        "channel_received": channel_received,
        "method": method,
        "scope": scope,
        "received_note": received_note,
    }
    payload.update(overrides)
    return _compact(payload)


def revocation_validate_payload(
    validation_note: str = "Identity verified", **overrides: Any
) -> Payload:
    """Input for POST /compliance/revocation-requests/{id}/validate."""
    payload = {"validation_note": validation_note}
    payload.update(overrides)
    return _compact(payload)


def revocation_reject_payload(rejection_reason: str, **overrides: Any) -> Payload:
    """Input for POST /compliance/revocation-requests/{id}/reject."""
    payload = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return _compact(payload)


def revocation_propagate_payload(
    target_systems: Optional[List[str]] = None, **overrides: Any
) -> Payload:
    """Input for POST /compliance/revocation-requests/{id}/propagate."""
    payload = {
        "target_systems": ["DIALER", "CRM"] if target_systems is None else target_systems
    }
    payload.update(overrides)
    return _compact(payload)


# ---------------------------------------------------------------------------
# SuppressionEntry
# ---------------------------------------------------------------------------


def suppression_entry_payload(
    phone_number: str,
    list_type: str = ListType.NATIONAL,
    source: str = SuppressionSource.FTC_DNC_DOWNLOAD,
    source_refreshed_at: str = "2026-08-01T00:00:00Z",
    state_code: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    """Input for POST /compliance/suppression-entries."""
    payload = {
        "list_type": list_type,
        "phone_number": phone_number,
        "state_code": state_code,
        "source": source,
        "source_refreshed_at": source_refreshed_at,
    }
    payload.update(overrides)
    return _compact(payload)


def suppression_remove_payload(
    removal_reason: str = RemovalReason.REGISTRY_DELISTING, **overrides: Any
) -> Payload:
    """Input for POST /compliance/suppression-entries/{id}/remove."""
    payload = {"removal_reason": removal_reason}
    payload.update(overrides)
    return _compact(payload)


# ---------------------------------------------------------------------------
# ScrubJob
# ---------------------------------------------------------------------------


def scrub_job_payload(
    campaign_id: str,
    expected_campaign_version: int,
    list_types: Optional[List[str]] = None,
    **overrides: Any,
) -> Payload:
    """Input for POST /compliance/scrub-jobs."""
    payload = {
        "campaign_id": campaign_id,
        "list_types": [ListType.NATIONAL, ListType.INTERNAL]
        if list_types is None
        else list_types,
        "expected_campaign_version": expected_campaign_version,
    }
    payload.update(overrides)
    return _compact(payload)


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------


def campaign_payload(
    dialer_profile_id: str,
    agent_script_id: str,
    name: str = "CA Aug Outreach",
    channel: str = Channel.VOICE,
    campaign_purpose: str = CampaignPurpose.MARKETING,
    target_state_codes: Optional[List[str]] = None,
    **overrides: Any,
) -> Payload:
    """Input for POST /compliance/campaigns."""
    payload = {
        "name": name,
        "channel": channel,
        "campaign_purpose": campaign_purpose,
        "target_state_codes": [STATE_CA]
        if target_state_codes is None
        else target_state_codes,
        "dialer_profile_id": dialer_profile_id,
        "agent_script_id": agent_script_id,
    }
    payload.update(overrides)
    return _compact(payload)


def campaign_launch_payload(
    expected_campaign_version: int,
    certification_note: str = "Certified for CA outreach",
    **overrides: Any,
) -> Payload:
    """Input for POST /compliance/campaigns/{id}/launch."""
    payload = {
        "certification_note": certification_note,
        "expected_campaign_version": expected_campaign_version,
    }
    payload.update(overrides)
    return _compact(payload)


def campaign_suspend_payload(
    suspension_note: str = "Manual hold", **overrides: Any
) -> Payload:
    """Input for POST /compliance/campaigns/{id}/suspend."""
    payload = {"suspension_note": suspension_note}
    payload.update(overrides)
    return _compact(payload)


def campaign_resume_payload(
    resume_note: str = "Cleared to resume", **overrides: Any
) -> Payload:
    """Input for POST /compliance/campaigns/{id}/resume."""
    payload = {"resume_note": resume_note}
    payload.update(overrides)
    return _compact(payload)


def campaign_close_payload(
    closure_note: str = "Programme complete", **overrides: Any
) -> Payload:
    """Input for POST /compliance/campaigns/{id}/close."""
    payload = {"closure_note": closure_note}
    payload.update(overrides)
    return _compact(payload)


# ---------------------------------------------------------------------------
# DialerProfile
# ---------------------------------------------------------------------------


def dialer_profile_payload(
    mode: str = DialerMode.PREDICTIVE,
    agents_available: int = 5,
    abandonment_limit_pct: Optional[float] = 50.0,
    amd_enabled: Optional[bool] = True,
    amd_abandon_on_machine: Optional[bool] = False,
    abandon_message_seconds: Optional[int] = 2,
    **overrides: Any,
) -> Payload:
    """Input for POST /compliance/dialer-profiles."""
    payload = {
        "mode": mode,
        "agents_available": agents_available,
        "abandonment_limit_pct": abandonment_limit_pct,
        "amd_enabled": amd_enabled,
        "amd_abandon_on_machine": amd_abandon_on_machine,
        "abandon_message_seconds": abandon_message_seconds,
    }
    payload.update(overrides)
    return _compact(payload)


def dialer_profile_approve_payload(
    waiver_reference: Optional[str] = None, **overrides: Any
) -> Payload:
    """Input for POST /compliance/dialer-profiles/{id}/approve."""
    payload = {"waiver_reference": waiver_reference}
    payload.update(overrides)
    return _compact(payload)


# ---------------------------------------------------------------------------
# AgentScript
# ---------------------------------------------------------------------------


DEFAULT_DISCLOSURE_BLOCK_TEXT = {
    DisclosureBlockType.IDENTIFICATION: "This call is from Example Outreach Services.",
    DisclosureBlockType.PURPOSE: "We are calling about your enquiry.",
    DisclosureBlockType.OPT_OUT: "Say stop at any time to be removed from our list.",
    DisclosureBlockType.RECORDING_NOTICE: "This call is being recorded.",
}


def disclosure_blocks(*block_types: str) -> List[Dict[str, str]]:
    """Build a ``disclosure_blocks`` list of objects with a type and its text."""
    chosen = block_types or (
        DisclosureBlockType.IDENTIFICATION,
        DisclosureBlockType.PURPOSE,
        DisclosureBlockType.OPT_OUT,
    )
    return [
        {
            "block_type": block_type,
            "text": DEFAULT_DISCLOSURE_BLOCK_TEXT.get(
                block_type, "Disclosure text for %s." % block_type
            ),
        }
        for block_type in chosen
    ]


def agent_script_payload(
    name: str = "CA VOICE Script",
    channel: str = Channel.VOICE,
    blocks: Optional[List[Dict[str, str]]] = None,
    recording_consent_mode: str = RecordingConsentMode.ONE_PARTY,
    covered_state_codes: Optional[List[str]] = None,
    **overrides: Any,
) -> Payload:
    """Input for POST /compliance/agent-scripts."""
    payload = {
        "name": name,
        "channel": channel,
        "disclosure_blocks": disclosure_blocks() if blocks is None else blocks,
        "recording_consent_mode": recording_consent_mode,
        "covered_state_codes": [STATE_CA]
        if covered_state_codes is None
        else covered_state_codes,
    }
    payload.update(overrides)
    return _compact(payload)


def agent_script_approve_payload(
    approval_note: str = "Disclosures cleared", **overrides: Any
) -> Payload:
    """Input for POST /compliance/agent-scripts/{id}/approve."""
    payload = {"approval_note": approval_note}
    payload.update(overrides)
    return _compact(payload)


def agent_script_request_changes_payload(
    change_note: str = "Add the recording notice", **overrides: Any
) -> Payload:
    """Input for POST /compliance/agent-scripts/{id}/request-changes."""
    payload = {"change_note": change_note}
    payload.update(overrides)
    return _compact(payload)


# ---------------------------------------------------------------------------
# CallingWindowPolicy
# ---------------------------------------------------------------------------


def calling_window_policy_payload(
    state_code: str = STATE_CA,
    window_start_local: str = "08:00",
    window_end_local: str = "21:00",
    recording_consent_regime: str = RecordingConsentRegime.ONE_PARTY,
    effective_from: str = "2026-07-01T00:00:00Z",
    effective_to: str = "2027-01-01T00:00:00Z",
    holiday_dates: Optional[List[str]] = None,
    supersedes_policy_id: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    """Input for POST /compliance/calling-window-policies."""
    payload = {
        "state_code": state_code,
        "window_start_local": window_start_local,
        "window_end_local": window_end_local,
        "recording_consent_regime": recording_consent_regime,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "holiday_dates": holiday_dates,
        "supersedes_policy_id": supersedes_policy_id,
    }
    payload.update(overrides)
    return _compact(payload)


def declare_emergency_payload(
    emergency_note: str = "Wildfire evacuation order", **overrides: Any
) -> Payload:
    """Input for POST /compliance/calling-window-policies/{id}/declare-emergency."""
    payload = {"emergency_note": emergency_note}
    payload.update(overrides)
    return _compact(payload)


# ---------------------------------------------------------------------------
# ContactAttempt
# ---------------------------------------------------------------------------


def contact_attempt_payload(
    campaign_id: str,
    contact_id: str,
    channel: str = Channel.VOICE,
    **overrides: Any,
) -> Payload:
    """Input for POST /compliance/contact-attempts."""
    payload = {
        "campaign_id": campaign_id,
        "contact_id": contact_id,
        "channel": channel,
    }
    payload.update(overrides)
    return _compact(payload)


def attempt_outcome_payload(
    outcome: str = AttemptOutcome.CONNECTED_LIVE,
    agent_connect_seconds: Optional[int] = None,
    abandon_message_played: Optional[bool] = None,
    **overrides: Any,
) -> Payload:
    """Input for POST /compliance/contact-attempts/{id}/outcome."""
    payload = {
        "outcome": outcome,
        "agent_connect_seconds": agent_connect_seconds,
        "abandon_message_played": abandon_message_played,
    }
    payload.update(overrides)
    return _compact(payload)


def attempt_void_payload(
    void_reason: str = VoidReason.COMPLIANCE_CORRECTION, **overrides: Any
) -> Payload:
    """Input for POST /compliance/contact-attempts/{id}/void."""
    payload = {"void_reason": void_reason}
    payload.update(overrides)
    return _compact(payload)


# ---------------------------------------------------------------------------
# Complaint
# ---------------------------------------------------------------------------


def complaint_payload(
    contact_id: str,
    campaign_id: str,
    source: str = ComplaintSource.FTC,
    alleged_violation_type: str = AllegedViolationType.DNC_VIOLATION,
    narrative: str = "Consumer reports calls after asking to stop.",
    litigation_flag: Optional[bool] = None,
    **overrides: Any,
) -> Payload:
    """Input for POST /compliance/complaints."""
    payload = {
        "contact_id": contact_id,
        "campaign_id": campaign_id,
        "source": source,
        "alleged_violation_type": alleged_violation_type,
        "narrative": narrative,
        "litigation_flag": litigation_flag,
    }
    payload.update(overrides)
    return _compact(payload)


def complaint_substantiate_payload(
    willful: bool = False, finding_note: str = "Violation confirmed", **overrides: Any
) -> Payload:
    """Input for POST /compliance/complaints/{id}/substantiate."""
    payload = {"willful": willful, "finding_note": finding_note}
    payload.update(overrides)
    return _compact(payload)


def complaint_dismiss_payload(
    dismissal_note: str = "No violation found", **overrides: Any
) -> Payload:
    """Input for POST /compliance/complaints/{id}/dismiss."""
    payload = {"dismissal_note": dismissal_note}
    payload.update(overrides)
    return _compact(payload)
