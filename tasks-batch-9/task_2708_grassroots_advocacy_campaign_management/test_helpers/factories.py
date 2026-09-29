"""Payload builders for every create/transition body the contract accepts.

Each builder returns only the client-supplied fields, never a server-minted or
computed one, and every builder takes ``**overrides`` so a test can vary one
field without restating the rest. Money is always an integer count of cents and
counts are always integers, never strings.
"""

from typing import Any, Dict, List, Optional

from . import constants as C
from .types import (
    ACQUISITION_PETITION,
    CHAMBER_HOUSE,
    CHANNEL_EMAIL,
    CONSENT_ACTION_GRANT,
    LAWFUL_BASIS_OPT_IN_FORM,
    MILESTONE_FLOOR_VOTE,
    PARTNER_TIER_ANCHOR,
    STANCE_UNDECIDED,
    TEST_CELL_ECONOMIC_FRAME,
)


# --------------------------------------------------------------------------
# Campaign
# --------------------------------------------------------------------------

def campaign_payload(**overrides: Any) -> Dict[str, Any]:
    """A fundable campaign spanning the whole test calendar."""
    payload: Dict[str, Any] = {
        "name": "Fair Housing Now",
        "goal_statement": "Pass HB-1420 out of committee",
        "bill_reference": "HB-1420",
        "target_chamber": CHAMBER_HOUSE,
        "start_date": C.CAMPAIGN_START,
        "end_date": C.CAMPAIGN_END,
        "success_metric_target_actions": 500,
        "success_metric_target_supporters": 200,
        "funded_total_cents": 100000,
    }
    payload.update(overrides)
    return payload


def posture_override_payload(posture_override: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "posture_override": posture_override,
        "override_reason": "director judgement recorded for the audit trail",
    }
    payload.update(overrides)
    return payload


def message_test_resolution_payload(test_cell: str, winning_message_variant_id: str,
                                   **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "test_cell": test_cell,
        "winning_message_variant_id": winning_message_variant_id,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Milestone
# --------------------------------------------------------------------------

def milestone_payload(campaign_id: str, window_start: str, window_end: str,
                      kind: str = MILESTONE_FLOOR_VOTE,
                      **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "campaign_id": campaign_id,
        "kind": kind,
        "label": f"{kind} sitting",
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def milestone_reschedule_payload(window_start: str, window_end: str,
                                 **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Legislator
# --------------------------------------------------------------------------

def legislator_payload(campaign_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "campaign_id": campaign_id,
        "full_name": "Rep. Alba",
        "district_code": "HD-14",
        "chamber": CHAMBER_HOUSE,
        "stance": STANCE_UNDECIDED,
    }
    payload.update(overrides)
    return payload


def stance_update_payload(stance: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "stance": stance,
        "evidence_note": "district office confirmed the position in writing",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Supporter
# --------------------------------------------------------------------------

def supporter_payload(campaign_id: str,
                      full_name: str = "Sup One",
                      email: str = "s1@example.org",
                      district_code: str = "HD-14",
                      initial_consent_channels: Optional[List[str]] = None,
                      **overrides: Any) -> Dict[str, Any]:
    """A supporter enrolled with a lawful basis for the channels named.

    ``initial_consent_channels`` defaults to EMAIL only. A supporter who is to
    hold SMS or PHONE consent also needs a ``phone``, which the caller supplies
    through overrides or through :func:`supporter_payload_with_phone`.
    """
    payload: Dict[str, Any] = {
        "campaign_id": campaign_id,
        "full_name": full_name,
        "email": email,
        "district_code": district_code,
        "acquisition_source": ACQUISITION_PETITION,
        "initial_consent_channels": (
            [CHANNEL_EMAIL] if initial_consent_channels is None
            else list(initial_consent_channels)
        ),
        "lawful_basis": LAWFUL_BASIS_OPT_IN_FORM,
        "consent_source_reference": "web-form-1",
    }
    payload.update(overrides)
    return payload


def supporter_payload_with_phone(campaign_id: str,
                                 phone: str = "+15550100001",
                                 **overrides: Any) -> Dict[str, Any]:
    """A supporter carrying a phone number, for SMS or PHONE consent."""
    payload = supporter_payload(campaign_id, **overrides)
    payload.setdefault("phone", phone)
    if "phone" in overrides:
        payload["phone"] = overrides["phone"]
    return payload


# --------------------------------------------------------------------------
# Consent events
# --------------------------------------------------------------------------

def consent_event_payload(supporter_id: str, channel: str, action: str,
                          **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "supporter_id": supporter_id,
        "channel": channel,
        "action": action,
        "source_reference": "consent-desk-1",
    }
    if action == CONSENT_ACTION_GRANT:
        payload["lawful_basis"] = LAWFUL_BASIS_OPT_IN_FORM
    payload.update(overrides)
    return payload


def grant_payload(supporter_id: str, channel: str, **overrides: Any) -> Dict[str, Any]:
    return consent_event_payload(supporter_id, channel, "GRANT", **overrides)


def revoke_payload(supporter_id: str, channel: str, **overrides: Any) -> Dict[str, Any]:
    return consent_event_payload(supporter_id, channel, "REVOKE", **overrides)


# --------------------------------------------------------------------------
# Segment
# --------------------------------------------------------------------------

def segment_payload(campaign_id: str, name: str = "Email openers",
                    rule_required_channel: str = CHANNEL_EMAIL,
                    **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "campaign_id": campaign_id,
        "name": name,
        "rule_required_channel": rule_required_channel,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Message variant
# --------------------------------------------------------------------------

def variant_payload(campaign_id: str,
                    channel_scope: Optional[List[str]] = None,
                    test_cell: str = TEST_CELL_ECONOMIC_FRAME,
                    **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "campaign_id": campaign_id,
        "test_cell": test_cell,
        "headline": "Vote yes on HB-1420",
        "body": "Ask your representative to vote yes on HB-1420.",
        "channel_scope": ([CHANNEL_EMAIL] if channel_scope is None
                          else list(channel_scope)),
    }
    payload.update(overrides)
    return payload


def variant_submit_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"submission_note": "ready for compliance review"}
    payload.update(overrides)
    return payload


def review_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": decision,
        "review_note": ("copy is compliant" if decision == "APPROVE"
                        else "tighten the disclosure line"),
    }
    payload.update(overrides)
    return payload


def variant_reopen_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reopen_reason": "bill number changed in committee"}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Coalition partner and endorsement
# --------------------------------------------------------------------------

def partner_payload(campaign_id: str, org_name: str = "Anchor Housing Alliance",
                    tier: str = PARTNER_TIER_ANCHOR,
                    **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "campaign_id": campaign_id,
        "org_name": org_name,
        "tier": tier,
        "branding_asset_ref": "brand/anchor.svg",
    }
    payload.update(overrides)
    return payload


def partner_withdraw_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"withdraw_reason": "board reallocated the budget"}
    payload.update(overrides)
    return payload


def endorsement_payload(partner_id: str, message_variant_id: str,
                        expected_variant_version: int,
                        **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "partner_id": partner_id,
        "message_variant_id": message_variant_id,
        "discipline_pledge": True,
        "talking_points_ack": True,
        "expected_variant_version": expected_variant_version,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Activation
# --------------------------------------------------------------------------

def activation_payload(campaign_id: str, segment_id: str, message_variant_id: str,
                       window_start: str, window_end: str,
                       expected_segment_version: int,
                       channel: str = CHANNEL_EMAIL,
                       min_viable_reach: int = 1,
                       **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "campaign_id": campaign_id,
        "segment_id": segment_id,
        "message_variant_id": message_variant_id,
        "channel": channel,
        "window_start": window_start,
        "window_end": window_end,
        "expected_segment_version": expected_segment_version,
        "min_viable_reach": min_viable_reach,
    }
    payload.update(overrides)
    return payload


def activation_clear_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"clearance_note": "consent evidence sampled"}
    payload.update(overrides)
    return payload


def activation_block_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"block_reason": "coalition discipline breach"}
    payload.update(overrides)
    return payload


def activation_complete_payload(delivered_count: int, bounced_count: int,
                                **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "delivered_count": delivered_count,
        "bounced_count": bounced_count,
    }
    payload.update(overrides)
    return payload


def activation_abort_payload(abort_reason: str = "budget pulled",
                             **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"abort_reason": abort_reason}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Action record
# --------------------------------------------------------------------------

def action_record_payload(supporter_id: str, channel: str = CHANNEL_EMAIL,
                          **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "supporter_id": supporter_id,
        "channel": channel,
    }
    payload.update(overrides)
    return payload


def acknowledge_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"acknowledgement_note": "logged by the field desk"}
    payload.update(overrides)
    return payload


def thank_payload(thank_channel: str = CHANNEL_EMAIL, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"thank_channel": thank_channel}
    payload.update(overrides)
    return payload


def dispute_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"dispute_reason": "supporter denies making the contact"}
    payload.update(overrides)
    return payload


def dispute_resolution_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "outcome": outcome,
        "resolution_note": "call log reviewed with the district office",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Spokesperson
# --------------------------------------------------------------------------

def spokesperson_payload(supporter_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "supporter_id": supporter_id,
        "story_summary": "Lost a rental to an eviction notice while pregnant.",
    }
    payload.update(overrides)
    return payload


def training_advancement_payload(to_level: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "to_level": to_level,
        "session_reference": f"session-{to_level.lower()}-1",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# District meeting
# --------------------------------------------------------------------------

def meeting_payload(campaign_id: str, legislator_id: str,
                    lead_spokesperson_id: str,
                    window_start: str, window_end: str,
                    location_district_code: str = "HD-14",
                    **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "campaign_id": campaign_id,
        "legislator_id": legislator_id,
        "lead_spokesperson_id": lead_spokesperson_id,
        "location_district_code": location_district_code,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def meeting_response_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if decision == "DECLINE":
        payload["decline_reason"] = "the member is in committee that morning"
    payload.update(overrides)
    return payload


def meeting_complete_payload(attendee_count: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"attendee_count": attendee_count}
    payload.update(overrides)
    return payload
