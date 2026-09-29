"""Request payload factories.

Every factory returns only the fields a caller is allowed to supply; system
fields (identifiers, timestamps, versions, statuses and derived counters) are
minted by the server and are never included.  Each factory accepts keyword
overrides so a test can vary exactly the one field it cares about.
"""

from .constants import CLOCK_STARTUP_UTC

# ---------------------------------------------------------------------------
# Canonical scenario values reused across the suite so that arithmetic
# expectations stay stable.
# ---------------------------------------------------------------------------

DEFAULT_EVENT_START_UTC = "2026-10-15T16:00:00Z"
DEFAULT_EVENT_END_UTC = "2026-10-15T18:00:00Z"
DEFAULT_PROPOSAL_VALID_UNTIL_UTC = "2026-09-20T00:00:00Z"
DEFAULT_QUOTED_FEE_CENTS = 1_275_000


# ---------------------------------------------------------------------------
# Speaker (PRD §3.1)
# ---------------------------------------------------------------------------


def speaker_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dana Reyes",
        "topics": ["AI_STRATEGY", "LEADERSHIP"],
        "fee_floor_cents": 1_000_000,
        "fee_ceiling_cents": 2_000_000,
        "travel_class": "PREMIUM",
        "travel_buffer_days": 1,
        "tax_form_status": "ON_FILE",
    }
    payload.update(overrides)
    return payload


def minimal_speaker_payload(**overrides) -> dict:
    """Only the fields the PRD requires; the rest fall back to defaults."""
    payload = {
        "full_name": "Ines Duarte",
        "topics": ["LEADERSHIP"],
        "fee_floor_cents": 500_000,
        "fee_ceiling_cents": 1_500_000,
        "travel_class": "ECONOMY",
    }
    payload.update(overrides)
    return payload


def second_speaker_payload(**overrides) -> dict:
    payload = {
        "full_name": "Rafael Cho",
        "topics": ["LEADERSHIP", "AI_STRATEGY"],
        "fee_floor_cents": 900_000,
        "fee_ceiling_cents": 1_800_000,
        "travel_class": "ECONOMY",
        "travel_buffer_days": 1,
        "tax_form_status": "ON_FILE",
    }
    payload.update(overrides)
    return payload


def speaker_update_payload(**overrides) -> dict:
    payload = {
        "fee_floor_cents": 1_200_000,
        "fee_ceiling_cents": 2_400_000,
        "travel_class": "BUSINESS",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Client (PRD §3.2)
# ---------------------------------------------------------------------------


def client_payload(**overrides) -> dict:
    payload = {
        "org_name": "Meridian Health",
        "industry_code": "HEALTHCARE",
        "primary_contact_email": "ops@meridian.example",
    }
    payload.update(overrides)
    return payload


def second_client_payload(**overrides) -> dict:
    payload = {
        "org_name": "Northwind Care",
        "industry_code": "HEALTHCARE",
        "primary_contact_email": "events@northwind.example",
    }
    payload.update(overrides)
    return payload


def client_update_payload(**overrides) -> dict:
    payload = {"primary_contact_email": "billing@meridian.example"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Inquiry (PRD §3.2)
# ---------------------------------------------------------------------------


def inquiry_payload(client_id: str, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "required_topic": "AI_STRATEGY",
        "event_start_utc": DEFAULT_EVENT_START_UTC,
        "event_end_utc": DEFAULT_EVENT_END_UTC,
        "is_virtual": False,
        "audience_size": 800,
        "budget_cents": 1_600_000,
        "objective_tags": ["STRATEGY"],
    }
    payload.update(overrides)
    return payload


def qualify_payload(outcome: str = "QUALIFY", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def disqualify_payload(note: str = "budget withdrawn by the client", **overrides) -> dict:
    payload = {"outcome": "DISQUALIFY", "qualification_note": note}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Proposal and options (PRD §3.3)
# ---------------------------------------------------------------------------


def proposal_payload(expected_inquiry_version: int, **overrides) -> dict:
    payload = {
        "expected_inquiry_version": expected_inquiry_version,
        "valid_until_utc": DEFAULT_PROPOSAL_VALID_UNTIL_UTC,
    }
    payload.update(overrides)
    return payload


def proposal_option_payload(proposal_id: str, speaker_id: str, **overrides) -> dict:
    payload = {
        "proposal_id": proposal_id,
        "speaker_id": speaker_id,
        "quoted_fee_cents": DEFAULT_QUOTED_FEE_CENTS,
        "rank_no": 1,
        "travel_allowance_cents": 0,
    }
    payload.update(overrides)
    return payload


def revision_request_payload(**overrides) -> dict:
    payload = {"revision_note": "the client asks for a lower headline fee"}
    payload.update(overrides)
    return payload


def proposal_decline_payload(**overrides) -> dict:
    payload = {"decline_reason": "the client shelved the event"}
    payload.update(overrides)
    return payload


def select_option_payload(option_id: str, **overrides) -> dict:
    payload = {"option_id": option_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Engagement lifecycle (PRD §3.4, §3.5, §3.7, §3.8)
# ---------------------------------------------------------------------------


def engagement_decline_payload(**overrides) -> dict:
    payload = {"decline_reason": "a scheduling conflict emerged"}
    payload.update(overrides)
    return payload


def contract_payload(**overrides) -> dict:
    payload = {
        "cancellation_schedule_code": "STANDARD",
        "travel_policy_code": "POLICY_B",
        "recording_rights": "NONE",
        "technical_rider_code": "STANDARD_AV",
        "exclusivity_days": 0,
    }
    payload.update(overrides)
    return payload


def signature_payload(signature_name: str, **overrides) -> dict:
    payload = {"signature_name": signature_name}
    payload.update(overrides)
    return payload


def cancellation_payload(reason: str = "the client cancelled the conference", **overrides) -> dict:
    payload = {"cancellation_reason": reason}
    payload.update(overrides)
    return payload


def commission_adjustment_payload(
    new_commission_pct: float, expected_engagement_version: int, **overrides
) -> dict:
    payload = {
        "new_commission_pct": new_commission_pct,
        "expected_engagement_version": expected_engagement_version,
        "reason": "a negotiated concession on the headline rate",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Travel expenses (PRD §3.6)
# ---------------------------------------------------------------------------


def travel_expense_payload(**overrides) -> dict:
    payload = {
        "receipts_cents": 63_750,
        "travel_days": 1,
        "distance_band": "REGIONAL",
        "memo": "rail fare and one hotel night",
    }
    payload.update(overrides)
    return payload


def travel_rejection_payload(**overrides) -> dict:
    payload = {"rejection_reason": "outside the rider"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Invoices and remittances (PRD §3.7)
# ---------------------------------------------------------------------------


def payment_payload(amount_cents: int, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def void_payload(**overrides) -> dict:
    payload = {"void_reason": "issued against the wrong client record"}
    payload.update(overrides)
    return payload


def remittance_payout_payload(reference: str = "WIRE-771", **overrides) -> dict:
    payload = {"payment_reference": reference}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Feedback and tiering (PRD §3.9)
# ---------------------------------------------------------------------------


def feedback_payload(
    content_score: int = 5, logistics_score: int = 4, **overrides
) -> dict:
    payload = {
        "content_score": content_score,
        "logistics_score": logistics_score,
        "rebook_intent": True,
        "comment": "excellent",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Calendar holds (PRD §3.1)
# ---------------------------------------------------------------------------


def speaker_hold_payload(speaker_id: str, **overrides) -> dict:
    payload = {
        "speaker_id": speaker_id,
        "kind": "BLACKOUT",
        "hold_start_utc": "2026-10-14T00:00:00Z",
        "hold_end_utc": "2026-10-14T23:59:59Z",
        "reason": "personal leave",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Exclusivity and non-circumvention (PRD §3.5, §3.9)
# ---------------------------------------------------------------------------


def exclusivity_waiver_payload(**overrides) -> dict:
    payload = {"waiver_reason": "beneficiary consented in writing"}
    payload.update(overrides)
    return payload


def circumvention_claim_payload(
    client_id: str,
    speaker_id: str,
    source_engagement_id: str,
    direct_event_date_utc: str,
    direct_fee_cents: int,
    **overrides,
) -> dict:
    payload = {
        "client_id": client_id,
        "speaker_id": speaker_id,
        "source_engagement_id": source_engagement_id,
        "direct_event_date_utc": direct_event_date_utc,
        "direct_fee_cents": direct_fee_cents,
    }
    payload.update(overrides)
    return payload


def claim_resolution_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome, "resolution_note": "direct rebooking confirmed"}
    payload.update(overrides)
    return payload


def claim_settlement_payload(settled_cents: int, **overrides) -> dict:
    payload = {
        "outcome": "SETTLE",
        "settled_cents": settled_cents,
        "resolution_note": "commission recovered in full",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------


def clock_payload(to_iso8601: str = CLOCK_STARTUP_UTC) -> dict:
    return {"to_iso8601": to_iso8601}
