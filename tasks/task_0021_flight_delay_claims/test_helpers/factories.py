"""Payload factories — one per entity, input fields only (PRD §3 + §4)."""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_CURRENCY,
    DEFAULT_DEDUCTIBLE_CENTS,
    DEFAULT_POLICY_LIMIT_CENTS,
    DEFAULT_QUOTA_TOTAL_CENTS,
)


# ---------------------------------------------------------------------------
# Unique-id helpers (avoid collisions across parallel tests)
# ---------------------------------------------------------------------------

def unique_pnr() -> str:
    """Return a unique 6-char PNR-style code (uppercase alphanumeric)."""
    return ("PNR" + uuid.uuid4().hex[:6].upper())[:9]


def unique_doc_id() -> str:
    return f"DOC-{uuid.uuid4().hex[:10]}"


def unique_carrier_code() -> str:
    """Two-letter IATA-style carrier code derived from a UUID."""
    h = uuid.uuid4().hex.upper()
    return h[0] + h[1]


def unique_flight_number() -> str:
    return str(uuid.uuid4().int % 10000).zfill(3)


def unique_source_event_id() -> str:
    return f"EVT-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Insurer (PRD §2.6)
# ---------------------------------------------------------------------------

def create_insurer_payload(name: str = "Test Insurer", currency: str = DEFAULT_CURRENCY,
                            **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"name": name, "currency": currency}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Policy (PRD §3.1)
# ---------------------------------------------------------------------------

def create_policy_payload(
    *,
    policy_holder_name: str = "Alice Example",
    policy_holder_doc_id: Optional[str] = None,
    effective_from_epoch_ms: int = 0,
    effective_to_epoch_ms: int = 10_000_000_000_000,
    waiting_period_ms: int = 0,
    delay_basis: str = "DEPARTURE",
    payout_mode: str = "FIXED",
    reimbursement_rate_bps: int = 0,
    deductible_cents: int = DEFAULT_DEDUCTIBLE_CENTS,
    policy_limit_cents: int = DEFAULT_POLICY_LIMIT_CENTS,
    claim_quota_total_cents: int = DEFAULT_QUOTA_TOTAL_CENTS,
    excluded_delay_causes: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Build a Policy creation payload per PRD §3.1.

    All defaults align with PRD §3.1 ("optional waiting_period_ms ... defaulting
    to 0", "deductible_cents applied once per claim (defaulting to 0)") except
    deductible/limit/quota which carry test-friendly small numbers.
    """
    payload: Dict[str, Any] = {
        "policy_holder_name": policy_holder_name,
        "policy_holder_doc_id": policy_holder_doc_id or unique_doc_id(),
        "effective_from_epoch_ms": effective_from_epoch_ms,
        "effective_to_epoch_ms": effective_to_epoch_ms,
        "waiting_period_ms": waiting_period_ms,
        "delay_basis": delay_basis,
        "payout_mode": payout_mode,
        "reimbursement_rate_bps": reimbursement_rate_bps,
        "deductible_cents": deductible_cents,
        "policy_limit_cents": policy_limit_cents,
        "claim_quota_total_cents": claim_quota_total_cents,
    }
    if excluded_delay_causes is not None:
        payload["excluded_delay_causes"] = excluded_delay_causes
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Flight (PRD §3.2)
# ---------------------------------------------------------------------------

def create_flight_payload(
    *,
    carrier_code: Optional[str] = None,
    flight_number: Optional[str] = None,
    origin_airport: str = "FRA",
    destination_airport: str = "JFK",
    scheduled_departure_epoch_ms: int = 10_000_000,
    scheduled_arrival_epoch_ms: int = 15_000_000,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "carrier_code": carrier_code or unique_carrier_code(),
        "flight_number": flight_number or unique_flight_number(),
        "origin_airport": origin_airport,
        "destination_airport": destination_airport,
        "scheduled_departure_epoch_ms": scheduled_departure_epoch_ms,
        "scheduled_arrival_epoch_ms": scheduled_arrival_epoch_ms,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# FlightStatusEvent (PRD §2.7)
# ---------------------------------------------------------------------------

def flight_event_payload(
    *,
    source: str,
    reported_status: str,
    source_event_id: Optional[str] = None,
    reported_actual_departure_epoch_ms: Optional[int] = None,
    reported_actual_arrival_epoch_ms: Optional[int] = None,
    reported_cause: Optional[str] = None,
    report_epoch_ms: int = 0,
    **overrides,
) -> Dict[str, Any]:
    """Build a FlightStatusEvent payload per PRD §2.7."""
    payload: Dict[str, Any] = {
        "source": source,
        "source_event_id": source_event_id or unique_source_event_id(),
        "reported_status": reported_status,
        "report_epoch_ms": report_epoch_ms,
    }
    if reported_actual_departure_epoch_ms is not None:
        payload["reported_actual_departure_epoch_ms"] = reported_actual_departure_epoch_ms
    if reported_actual_arrival_epoch_ms is not None:
        payload["reported_actual_arrival_epoch_ms"] = reported_actual_arrival_epoch_ms
    if reported_cause is not None:
        payload["reported_cause"] = reported_cause
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Ticket (PRD §3.3)
# ---------------------------------------------------------------------------

def create_ticket_payload(
    *,
    flight_id: str,
    passenger_name: str = "Alice Example",
    passenger_doc_id: Optional[str] = None,
    pnr_code: Optional[str] = None,
    policy_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "flight_id": flight_id,
        "passenger_name": passenger_name,
        "passenger_doc_id": passenger_doc_id or unique_doc_id(),
        "pnr_code": pnr_code or unique_pnr(),
    }
    if policy_id is not None:
        payload["policy_id"] = policy_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Claim (PRD §3.4)
# ---------------------------------------------------------------------------

def create_claim_payload(
    *,
    ticket_ids: List[str],
    segments: Optional[List[Dict[str, Any]]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Claim creation: ticket_ids is the only mandatory body input per PRD §3.4.

    PRD §3.6 indicates the per-segment input field claimed_actual_loss_cents is
    "set via /claims body" for ACTUAL_LOSS-mode tests; we expose it via the
    optional `segments` array, mirroring the difficulty-design recipes
    (e.g. tiered_compensation_three_input_nonlinear).
    """
    payload: Dict[str, Any] = {"ticket_ids": list(ticket_ids)}
    if segments is not None:
        payload["segments"] = segments
    payload.update(overrides)
    return payload


def claim_segment_input(*, ticket_id: str, claimed_actual_loss_cents: int = 0) -> Dict[str, Any]:
    """Helper for the optional `segments` array on /claims POST."""
    return {"ticket_id": ticket_id, "claimed_actual_loss_cents": claimed_actual_loss_cents}


# ---------------------------------------------------------------------------
# Claim review actions (PRD §3.4)
# ---------------------------------------------------------------------------

def submit_review_payload(*, assigned_reviewer_id: str) -> Dict[str, Any]:
    """PRD §3.4: 'A ClaimsReviewer submits a matched claim for review,
    providing an assigned_reviewer_id in the request body that the server
    records on the claim.'"""
    return {"assigned_reviewer_id": assigned_reviewer_id}


def approve_claim_payload(*, assigned_approver_id: str) -> Dict[str, Any]:
    """PRD §3.4: 'A ClaimsApprover advances a claim from UNDER_REVIEW to
    APPROVED by supplying an assigned_approver_id in the request body (which
    must equal the caller's X-User-ID).'"""
    return {"assigned_approver_id": assigned_approver_id}


def reject_claim_payload(*, rejection_reason: str) -> Dict[str, Any]:
    """PRD §3.4: 'A reject from UNDER_REVIEW ... requires a rejection_reason in
    the request body drawn from EXCLUDED_CAUSE, WAITING_PERIOD,
    DELAY_BELOW_THRESHOLD, or MANUAL_DENY.'"""
    return {"rejection_reason": rejection_reason}


# ---------------------------------------------------------------------------
# Payout batch (PRD §3.8 / §3.9)
# ---------------------------------------------------------------------------

def create_batch_payload(*, flight_id: str, claim_ids: List[str]) -> Dict[str, Any]:
    return {"flight_id": flight_id, "claim_ids": list(claim_ids)}


def approve_batch_payload(*, assigned_batch_approver_id: str) -> Dict[str, Any]:
    return {"assigned_batch_approver_id": assigned_batch_approver_id}


def reject_batch_payload(*, reason: str = "no longer needed") -> Dict[str, Any]:
    return {"reason": reason}


def execute_batch_payload(*, assigned_batch_executor_id: str) -> Dict[str, Any]:
    return {"assigned_batch_executor_id": assigned_batch_executor_id}


# ---------------------------------------------------------------------------
# Manual review (PRD §3.3)
# ---------------------------------------------------------------------------

def resolve_bind_payload(*, resolved_policy_id: str) -> Dict[str, Any]:
    return {"resolved_policy_id": resolved_policy_id}


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def suspend_policy_payload(*, reason: str = "test suspend") -> Dict[str, Any]:
    """PRD §3.1: suspend supplies a `reason` in the request body."""
    return {"reason": reason}


def clock_advance_delta_payload(*, delta_ms: int) -> Dict[str, Any]:
    return {"delta_ms": delta_ms}


def clock_advance_to_payload(*, to_epoch_ms: int) -> Dict[str, Any]:
    return {"to_epoch_ms": to_epoch_ms}
