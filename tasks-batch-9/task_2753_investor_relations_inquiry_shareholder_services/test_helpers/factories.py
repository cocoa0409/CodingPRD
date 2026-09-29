"""Request-payload factories.

Each factory emits only the client-supplied inputs named by the PRD for that
operation. Optional inputs are omitted unless a value is passed, so that the
declared defaults stay observable. Monetary amounts are whole cents and are
always emitted as JSON numbers, never as strings (PRD 2.9).
"""

from typing import Any, Dict, Optional

from .constants import (
    ACK_DECISION_ACKNOWLEDGE,
    CLASS_PUBLIC_DOMAIN,
    CONTACT_INSTITUTIONAL_HOLDER,
    DISCLOSURE_FORM_8K,
    EVENT_CONFERENCE,
    INSTRUCTION_DIVIDEND_PAYMENT,
    METRIC_EPS,
    SERVICING_SET_THREAT_LEVEL,
    TOPIC_OTHER,
)


def _with_optional(payload: Dict[str, Any], **optional: Any) -> Dict[str, Any]:
    for key, value in optional.items():
        if value is not None:
            payload[key] = value
    return payload


# ---------------------------------------------------------------------------
# Company (PRD 3.1)
# ---------------------------------------------------------------------------
def company_payload(
    ticker: str = "IRC",
    legal_name: str = "Investor Relations Corp",
    shares_outstanding: int = 1000000,
    dividend_reserve_cents: Optional[int] = None,
    blackout_window_start: Optional[str] = None,
    blackout_window_end: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ticker": ticker,
        "legal_name": legal_name,
        "shares_outstanding": shares_outstanding,
    }
    return _with_optional(
        payload,
        dividend_reserve_cents=dividend_reserve_cents,
        blackout_window_start=blackout_window_start,
        blackout_window_end=blackout_window_end,
    )


# ---------------------------------------------------------------------------
# Contact (PRD 3.2)
# ---------------------------------------------------------------------------
def contact_payload(
    company_id: str,
    contact_type: str = CONTACT_INSTITUTIONAL_HOLDER,
    display_name: str = "Register Contact",
    email: str = "contact@holders.test",
    shares_held: Optional[int] = None,
    nda_on_file: Optional[bool] = None,
    coverage_status: Optional[str] = None,
    activist_flag: Optional[bool] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "company_id": company_id,
        "contact_type": contact_type,
        "display_name": display_name,
        "email": email,
    }
    return _with_optional(
        payload,
        shares_held=shares_held,
        nda_on_file=nda_on_file,
        coverage_status=coverage_status,
        activist_flag=activist_flag,
    )


def position_payload(shares_held: int, expected_company_version: int) -> Dict[str, Any]:
    return {
        "shares_held": shares_held,
        "expected_company_version": expected_company_version,
    }


def servicing_payload(
    action: str = SERVICING_SET_THREAT_LEVEL, threat_level: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    return _with_optional(payload, threat_level=threat_level)


# ---------------------------------------------------------------------------
# Disclosure (PRD 3.4)
# ---------------------------------------------------------------------------
def disclosure_payload(
    company_id: str,
    disclosure_type: str = DISCLOSURE_FORM_8K,
    fact_key: str = "8K-DEFAULT-01",
    metric: Optional[str] = None,
    period_label: Optional[str] = None,
    guidance_low: Optional[float] = None,
    guidance_high: Optional[float] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "company_id": company_id,
        "disclosure_type": disclosure_type,
        "fact_key": fact_key,
    }
    return _with_optional(
        payload,
        metric=metric,
        period_label=period_label,
        guidance_low=guidance_low,
        guidance_high=guidance_high,
    )


def guidance_disclosure_payload(
    company_id: str,
    fact_key: str,
    metric: str = METRIC_EPS,
    period_label: str = "FY2026",
    guidance_low: float = 2.00,
    guidance_high: float = 2.20,
) -> Dict[str, Any]:
    """A complete GUIDANCE_UPDATE payload that satisfies the publish gate."""
    return {
        "company_id": company_id,
        "disclosure_type": "GUIDANCE_UPDATE",
        "fact_key": fact_key,
        "metric": metric,
        "period_label": period_label,
        "guidance_low": guidance_low,
        "guidance_high": guidance_high,
    }


# ---------------------------------------------------------------------------
# Inquiry ticket (PRD 3.5)
# ---------------------------------------------------------------------------
def inquiry_payload(
    company_id: str,
    contact_id: str,
    topic_category: str = TOPIC_OTHER,
    subject: str = "A shareholder question.",
    requests_nonpublic_detail: Optional[bool] = None,
    linked_prior_inquiry_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "company_id": company_id,
        "contact_id": contact_id,
        "topic_category": topic_category,
        "subject": subject,
    }
    return _with_optional(
        payload,
        requests_nonpublic_detail=requests_nonpublic_detail,
        linked_prior_inquiry_id=linked_prior_inquiry_id,
    )


# ---------------------------------------------------------------------------
# Response draft (PRD 3.6)
# ---------------------------------------------------------------------------
def response_draft_payload(
    inquiry_id: str,
    body_text: str = "Nothing beyond our published disclosures.",
    disclosure_class: str = CLASS_PUBLIC_DOMAIN,
    cited_disclosure_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "inquiry_id": inquiry_id,
        "body_text": body_text,
        "disclosure_class": disclosure_class,
    }
    return _with_optional(payload, cited_disclosure_id=cited_disclosure_id)


def review_payload(
    decision: str,
    expected_inquiry_version: int,
    reviewer_note: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": decision,
        "expected_inquiry_version": expected_inquiry_version,
    }
    return _with_optional(payload, reviewer_note=reviewer_note)


def revise_payload(
    body_text: Optional[str] = None,
    disclosure_class: Optional[str] = None,
    cited_disclosure_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _with_optional(
        {},
        body_text=body_text,
        disclosure_class=disclosure_class,
        cited_disclosure_id=cited_disclosure_id,
    )


# ---------------------------------------------------------------------------
# Estimate submission (PRD 3.7)
# ---------------------------------------------------------------------------
def estimate_payload(
    contact_id: str,
    expected_contact_version: int,
    metric: str = METRIC_EPS,
    period_label: str = "FY2026",
    value: float = 2.0000,
) -> Dict[str, Any]:
    return {
        "contact_id": contact_id,
        "metric": metric,
        "period_label": period_label,
        "value": value,
        "expected_contact_version": expected_contact_version,
    }


# ---------------------------------------------------------------------------
# Roadshow event and meeting request (PRD 3.8)
# ---------------------------------------------------------------------------
def roadshow_event_payload(
    company_id: str,
    event_type: str = EVENT_CONFERENCE,
    venue_city: str = "London",
    window_start: str = "2026-09-01T13:00:00Z",
    window_end: str = "2026-09-01T18:00:00Z",
    slot_minutes: int = 30,
    capacity_slots: int = 2,
) -> Dict[str, Any]:
    return {
        "company_id": company_id,
        "event_type": event_type,
        "venue_city": venue_city,
        "window_start": window_start,
        "window_end": window_end,
        "slot_minutes": slot_minutes,
        "capacity_slots": capacity_slots,
    }


def meeting_request_payload(
    event_id: str,
    contact_id: str,
    requested_slot_start: str = "2026-09-01T13:00:00Z",
    requested_slot_end: str = "2026-09-01T13:30:00Z",
) -> Dict[str, Any]:
    return {
        "event_id": event_id,
        "contact_id": contact_id,
        "requested_slot_start": requested_slot_start,
        "requested_slot_end": requested_slot_end,
    }


# ---------------------------------------------------------------------------
# Transfer agent instruction (PRD 3.9)
# ---------------------------------------------------------------------------
def instruction_payload(
    company_id: str,
    instruction_type: str = INSTRUCTION_DIVIDEND_PAYMENT,
    record_date: Optional[str] = None,
    payable_date: Optional[str] = None,
    declared_rate_cents_per_share: Optional[float] = None,
    funding_mode: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "company_id": company_id,
        "instruction_type": instruction_type,
    }
    return _with_optional(
        payload,
        record_date=record_date,
        payable_date=payable_date,
        declared_rate_cents_per_share=declared_rate_cents_per_share,
        funding_mode=funding_mode,
        notes=notes,
    )


def dividend_instruction_payload(
    company_id: str,
    record_date: str = "2026-08-15",
    payable_date: str = "2026-08-25",
    declared_rate_cents_per_share: float = 1.0000,
    funding_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """A complete DIVIDEND_PAYMENT payload (rate is a number, not a string)."""
    return instruction_payload(
        company_id,
        instruction_type=INSTRUCTION_DIVIDEND_PAYMENT,
        record_date=record_date,
        payable_date=payable_date,
        declared_rate_cents_per_share=declared_rate_cents_per_share,
        funding_mode=funding_mode,
    )


def acknowledge_payload(
    decision: str = ACK_DECISION_ACKNOWLEDGE, rejection_reason: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    return _with_optional(payload, rejection_reason=rejection_reason)
