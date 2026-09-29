"""Payload factories with PRD-valid defaults.

Every factory returns a fresh dict whose defaults satisfy the shape rules of PRD
section 3, so a test only has to name the fields it is actually varying. Monetary
amounts are always integer cents (PRD 2.9) and never JSON strings.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    DELIVERY_MEDIUM_PAPER,
    DISPOSITION_FULL_RELEASE,
    FEE_VARIANT_ACTUAL_COST,
)

# ---------------------------------------------------------------------------
# Venues (PRD 3.1)
# ---------------------------------------------------------------------------


def venue_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "Council Chamber",
        "address": "1 Civic Plaza",
        "capacity": 120,
        "teardown_buffer_minutes": 30,
    }
    payload.update(overrides)
    return payload


def venue_update_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Meetings (PRD 3.1)
# ---------------------------------------------------------------------------


def meeting_payload(venue_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "body_type": "COUNCIL",
        "meeting_type": "REGULAR",
        "venue_id": venue_id,
        "scheduled_start": "2026-09-15T18:00:00Z",
        "scheduled_end": "2026-09-15T21:00:00Z",
        "quorum_required": 4,
    }
    payload.update(overrides)
    return payload


def reschedule_payload(
    scheduled_start: str, scheduled_end: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def convene_payload(present_member_count: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"present_member_count": present_member_count}
    payload.update(overrides)
    return payload


def cancel_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cancelled_reason": "Loss of quorum expected"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Agenda packets and items (PRD 3.2)
# ---------------------------------------------------------------------------


def agenda_packet_payload(expected_meeting_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_meeting_version": expected_meeting_version}
    payload.update(overrides)
    return payload


def agenda_item_payload(
    sequence_number: int = 1, item_type: str = "REPORT", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "sequence_number": sequence_number,
        "item_type": item_type,
        "title": "Quarterly finance report",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Numbering series and instruments (PRD 3.5)
# ---------------------------------------------------------------------------


def number_series_payload(
    series_year: int = 2026, instrument_class: str = "ORDINANCE", **overrides: Any
) -> Dict[str, Any]:
    prefix = "ORD" if instrument_class == "ORDINANCE" else "RES"
    payload: Dict[str, Any] = {
        "series_year": series_year,
        "instrument_class": instrument_class,
        "prefix": prefix,
    }
    payload.update(overrides)
    return payload


def ordinance_payload(number_series_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "instrument_class": "ORDINANCE",
        "ordinance_category": "GENERAL",
        "title": "Amending the noise ordinance",
        "full_text_length": 3000,
        "number_series_id": number_series_id,
    }
    payload.update(overrides)
    return payload


def code_amendment_payload(
    number_series_id: str,
    code_title_id: str,
    code_section_ref: str = "12.04.030",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "instrument_class": "ORDINANCE",
        "ordinance_category": "CODE_AMENDMENT",
        "title": f"Amending {code_section_ref}",
        "full_text_length": 1800,
        "number_series_id": number_series_id,
        "code_title_id": code_title_id,
        "code_section_ref": code_section_ref,
    }
    payload.update(overrides)
    return payload


def resolution_payload(number_series_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "instrument_class": "RESOLUTION",
        "title": "Commending the volunteer fire brigade",
        "full_text_length": 900,
        "number_series_id": number_series_id,
    }
    payload.update(overrides)
    return payload


def advance_reading_payload(meeting_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"meeting_id": meeting_id}
    payload.update(overrides)
    return payload


def veto_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"veto_reason": "Fiscal impact not addressed"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Motions and tallies (PRD 3.3)
# ---------------------------------------------------------------------------


def motion_payload(
    meeting_id: str,
    motion_type: str = "PROCEDURAL",
    majority_rule: str = "SIMPLE",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "meeting_id": meeting_id,
        "motion_type": motion_type,
        "majority_rule": majority_rule,
        "moved_by_member_id": "cm-01",
        "seconded_by_member_id": "cm-02",
    }
    payload.update(overrides)
    return payload


def tally_payload(
    yes_count: int,
    no_count: int,
    abstain_count: int = 0,
    recused_count: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "yes_count": yes_count,
        "no_count": no_count,
        "abstain_count": abstain_count,
        "recused_count": recused_count,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Minutes (PRD 3.4)
# ---------------------------------------------------------------------------


def minutes_narrative_payload(
    text_body: str = "The finance report was received and filed.", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"text_body": text_body}
    payload.update(overrides)
    return payload


def minutes_correction_payload(
    expected_minutes_version: int,
    corrected_text_body: str = "The finance report was received, filed and referred to committee.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_minutes_version": expected_minutes_version,
        "corrected_text_body": corrected_text_body,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Publication notices (PRD 3.6)
# ---------------------------------------------------------------------------


def publication_order_payload(
    publication_dates: List[str],
    column_inches: float = 20.0,
    affidavit_required: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "newspaper_name": "The Civic Ledger",
        "column_inches": column_inches,
        "publication_dates": publication_dates,
        "affidavit_required": affidavit_required,
    }
    payload.update(overrides)
    return payload


def certify_publication_payload(
    publication_completed_on: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"publication_completed_on": publication_completed_on}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Codification (PRD 3.7)
# ---------------------------------------------------------------------------


def code_title_payload(title_number: int = 12, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title_number": title_number,
        "name": "Streets, Sidewalks and Public Places",
    }
    payload.update(overrides)
    return payload


def supplement_cycle_payload(
    supplement_number: int = 7,
    window_open_on: str = "2026-07-01",
    window_close_on: str = "2026-09-30",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "supplement_number": supplement_number,
        "window_open_on": window_open_on,
        "window_close_on": window_close_on,
    }
    payload.update(overrides)
    return payload


def codification_submission_payload(
    cycle_id: str,
    instrument_id: str,
    expected_code_title_version: int,
    code_section_ref: str = "12.04.030",
    action: str = "ADD",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cycle_id": cycle_id,
        "instrument_id": instrument_id,
        "code_section_ref": code_section_ref,
        "action": action,
        "expected_code_title_version": expected_code_title_version,
    }
    payload.update(overrides)
    return payload


def decide_payload(decision: str = "ACCEPT", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def resolve_conflict_payload(
    resolution_basis: str, winning_submission_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"resolution_basis": resolution_basis}
    if winning_submission_id is not None:
        payload["winning_submission_id"] = winning_submission_id
    payload.update(overrides)
    return payload


def certify_cycle_payload(certified_on: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"certified_on": certified_on}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Public records requests (PRD 3.8)
# ---------------------------------------------------------------------------


def records_request_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "requester_name": "M. Rivera",
        "requester_email": "m.rivera@example.org",
        "subject_description": "Council correspondence 2025",
    }
    payload.update(overrides)
    return payload


def exemption_review_payload(
    exemption_claims: Optional[List[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "exemption_claims": (
            list(exemption_claims) if exemption_claims is not None else []
        )
    }
    payload.update(overrides)
    return payload


def fee_line(
    page_count: int,
    staff_minutes: int,
    delivery_medium: str = DELIVERY_MEDIUM_PAPER,
) -> Dict[str, Any]:
    return {
        "page_count": page_count,
        "staff_minutes": staff_minutes,
        "delivery_medium": delivery_medium,
    }


def assess_fee_payload(
    fee_lines: List[Dict[str, Any]],
    fee_schedule_variant: str = FEE_VARIANT_ACTUAL_COST,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "fee_schedule_variant": fee_schedule_variant,
        "fee_lines": list(fee_lines),
    }
    payload.update(overrides)
    return payload


def waive_fee_payload(waived_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "waived_cents": waived_cents,
        "waiver_reason": "Partial public-interest waiver",
    }
    payload.update(overrides)
    return payload


def payment_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def disposition_payload(
    disposition: str = DISPOSITION_FULL_RELEASE, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"disposition": disposition}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Retention schedule and destruction (PRD 3.9)
# ---------------------------------------------------------------------------


def record_series_payload(
    series_code: str = "CC-01",
    retention_years: int = 5,
    retention_trigger: str = "CREATION",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "series_code": series_code,
        "name": "Council correspondence",
        "retention_years": retention_years,
        "retention_trigger": retention_trigger,
    }
    payload.update(overrides)
    return payload


def record_series_update_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def accession_payload(
    item_count: int, accessioned_on: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "item_count": item_count,
        "accessioned_on": accessioned_on,
    }
    payload.update(overrides)
    return payload


def destruction_batch_payload(
    series_id: str, item_count: int, cutoff_on: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "series_id": series_id,
        "item_count": item_count,
        "cutoff_on": cutoff_on,
    }
    payload.update(overrides)
    return payload


def certify_batch_payload(certified_on: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"certified_on": certified_on}
    payload.update(overrides)
    return payload


def rescind_batch_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"rescind_reason": "Filed in error"}
    payload.update(overrides)
    return payload
