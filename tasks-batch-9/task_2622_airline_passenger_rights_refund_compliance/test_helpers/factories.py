"""Payload builders for every create/action endpoint.

Each builder produces the minimum valid body the PRD requires and lets a test
override or remove any field, so a test can express "the same body but without
the corrective-action narrative" without restating the whole payload.
"""

import itertools
from typing import Any, Dict, Optional

# Deterministic-but-unique natural keys, so two rows in one test never collide
# on carrier_code, email, record_locator or tag_number.
_counter = itertools.count(1)


def next_suffix() -> int:
    return next(_counter)


_CARRIER_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def unique_carrier_code() -> str:
    """Exactly two uppercase alphanumeric characters (PRD §2.5)."""
    n = next_suffix()
    return _CARRIER_ALPHABET[n % 36] + _CARRIER_ALPHABET[(n // 36) % 36]


def unique_email(local: str = "pat") -> str:
    return f"{local}{next_suffix()}@example.com"


def unique_record_locator() -> str:
    """Exactly six uppercase alphanumeric characters (PRD §2.5)."""
    n = next_suffix()
    body = f"{n:05d}"
    return f"R{body}"


def unique_tag_number() -> str:
    """Exactly ten characters (PRD §2.5)."""
    return f"BAG{next_suffix():07d}"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; an override of ``None`` removes the field entirely."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is None and key in payload:
            del payload[key]
        else:
            payload[key] = value
    return payload


# ─── Policy profile (PRD §2.9) ────────────────────────


def policy_profile_payload(carrier_code: str = "ZQ", **overrides) -> Dict[str, Any]:
    return _merge({"carrier_code": carrier_code}, overrides)


# ─── Passenger (PRD §3.1) ─────────────────────────────


def passenger_payload(
    email: str = "pat@example.com", full_name: str = "Pat Rivera", **overrides
) -> Dict[str, Any]:
    return _merge({"email": email, "full_name": full_name}, overrides)


# ─── Booking (PRD §3.1) ───────────────────────────────


def booking_payload(
    passenger_id: str,
    policy_profile_id: str,
    record_locator: str = "ABC123",
    total_fare_cents: int = 50000,
    payment_method: str = "CREDIT_CARD",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "passenger_id": passenger_id,
            "policy_profile_id": policy_profile_id,
            "record_locator": record_locator,
            "total_fare_cents": total_fare_cents,
            "payment_method": payment_method,
        },
        overrides,
    )


# ─── Flight segment (PRD §3.1) ────────────────────────


def flight_segment_payload(
    sequence_index: int = 1,
    flight_number: str = "ZQ410",
    origin_iata: str = "ORD",
    destination_iata: str = "DFW",
    is_international: bool = False,
    scheduled_departure_utc: str = "2026-08-10T12:00:00Z",
    scheduled_arrival_utc: str = "2026-08-10T14:00:00Z",
    segment_fare_cents: int = 50000,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "sequence_index": sequence_index,
            "flight_number": flight_number,
            "origin_iata": origin_iata,
            "destination_iata": destination_iata,
            "is_international": is_international,
            "scheduled_departure_utc": scheduled_departure_utc,
            "scheduled_arrival_utc": scheduled_arrival_utc,
            "segment_fare_cents": segment_fare_cents,
        },
        overrides,
    )


def second_segment_payload(segment_fare_cents: int = 60000, **overrides) -> Dict[str, Any]:
    """The DFW→LAX continuation used throughout the two-leg itineraries."""
    return flight_segment_payload(
        sequence_index=2,
        flight_number="ZQ520",
        origin_iata="DFW",
        destination_iata="LAX",
        scheduled_departure_utc="2026-08-10T16:00:00Z",
        scheduled_arrival_utc="2026-08-10T18:00:00Z",
        segment_fare_cents=segment_fare_cents,
        **overrides,
    )


# ─── Disruption and operations (PRD §3.2) ─────────────


def cancellation_payload(
    declared_at_utc: str = "2026-08-10T10:00:00Z", **overrides
) -> Dict[str, Any]:
    return _merge(
        {"disruption_type": "CANCELLATION", "declared_at_utc": declared_at_utc},
        overrides,
    )


def delay_payload(
    revised_arrival_utc: str,
    declared_at_utc: str = "2026-08-10T09:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "disruption_type": "DELAY",
            "declared_at_utc": declared_at_utc,
            "revised_arrival_utc": revised_arrival_utc,
        },
        overrides,
    )


def operation_payload(operation: str, occurred_at_utc: str, **overrides) -> Dict[str, Any]:
    return _merge({"operation": operation, "occurred_at_utc": occurred_at_utc}, overrides)


# ─── Ancillary purchases and checked bags (PRD §3.3) ──


def ancillary_payload(
    booking_id: str,
    flight_segment_id: str,
    service_type: str = "SEAT_SELECTION",
    amount_cents: int = 2000,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "booking_id": booking_id,
            "flight_segment_id": flight_segment_id,
            "service_type": service_type,
            "amount_cents": amount_cents,
        },
        overrides,
    )


def not_provided_payload(
    non_provision_reason: str = "EQUIPMENT_SWAP",
    occurred_at_utc: str = "2026-08-09T08:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "non_provision_reason": non_provision_reason,
            "occurred_at_utc": occurred_at_utc,
        },
        overrides,
    )


def checked_bag_payload(
    booking_id: str,
    tag_number: str = "BAG0000001",
    fee_cents: int = 4500,
    checked_at_utc: str = "2026-08-10T11:00:00Z",
    scheduled_delivery_utc: str = "2026-08-10T21:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "booking_id": booking_id,
            "tag_number": tag_number,
            "fee_cents": fee_cents,
            "checked_at_utc": checked_at_utc,
            "scheduled_delivery_utc": scheduled_delivery_utc,
        },
        overrides,
    )


def bag_delivered_payload(delivered_at_utc: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {"resolution": "DELIVERED", "delivered_at_utc": delivered_at_utc}, overrides
    )


def bag_lost_payload(loss_declared_at_utc: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {"resolution": "DECLARED_LOST", "loss_declared_at_utc": loss_declared_at_utc},
        overrides,
    )


# ─── Denied boarding (PRD §3.4) ───────────────────────


def denied_boarding_payload(
    booking_id: str,
    flight_segment_id: str,
    category: str = "INVOLUNTARY",
    one_way_fare_cents: int = 45000,
    substitute_arrival_utc: str = "2026-08-10T15:30:00Z",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "booking_id": booking_id,
            "flight_segment_id": flight_segment_id,
            "category": category,
            "one_way_fare_cents": one_way_fare_cents,
            "substitute_arrival_utc": substitute_arrival_utc,
        },
        overrides,
    )


def finalize_payload(
    finalized_at_utc: str = "2026-08-10T16:00:00Z", **overrides
) -> Dict[str, Any]:
    return _merge({"finalized_at_utc": finalized_at_utc}, overrides)


# ─── Tarmac delay events (PRD §3.5) ───────────────────


def tarmac_event_payload(
    flight_segment_id: str,
    tarmac_start_utc: str = "2026-08-10T12:00:00Z",
    phase: str = "DEPARTURE",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "flight_segment_id": flight_segment_id,
            "tarmac_start_utc": tarmac_start_utc,
            "phase": phase,
        },
        overrides,
    )


def deplane_payload(deplane_completed_utc: str, **overrides) -> Dict[str, Any]:
    return _merge({"deplane_completed_utc": deplane_completed_utc}, overrides)


def exemption_payload(
    exemption_declared_at_utc: str,
    exemption_reason: str = "ATC_DIRECTIVE",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "exemption_reason": exemption_reason,
            "exemption_declared_at_utc": exemption_declared_at_utc,
        },
        overrides,
    )


def file_report_payload(
    report_reference: str = "DOT-TARMAC-0001",
    filed_at_utc: str = "2026-08-11T09:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {"report_reference": report_reference, "filed_at_utc": filed_at_utc}, overrides
    )


# ─── Refund obligations (PRD §3.6, §3.7) ──────────────


def obligation_payload(
    booking_id: str,
    expected_booking_version: int,
    basis: str = "FARE",
    issuance_mode: str = "PROACTIVE",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "booking_id": booking_id,
            "basis": basis,
            "issuance_mode": issuance_mode,
            "expected_booking_version": expected_booking_version,
        },
        overrides,
    )


def elect_payload(election: str = "CASH", **overrides) -> Dict[str, Any]:
    return _merge({"election": election}, overrides)


def initiate_payload(processor_reference: str = "PROC-0001", **overrides) -> Dict[str, Any]:
    return _merge({"processor_reference": processor_reference}, overrides)


def complete_payload(
    outcome: str = "SUCCEEDED", failure_reason: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"outcome": outcome}
    if failure_reason is not None:
        base["failure_reason"] = failure_reason
    return _merge(base, overrides)


def void_payload(void_reason: str = "CREATED_IN_ERROR", **overrides) -> Dict[str, Any]:
    return _merge({"void_reason": void_reason}, overrides)


# ─── Consumer complaints (PRD §3.8) ───────────────────


def complaint_payload(
    booking_id: str,
    category: str = "REFUND",
    channel: str = "EMAIL",
    received_at_utc: str = "2026-08-05T09:00:00Z",
    summary: str = "Refund never arrived.",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "booking_id": booking_id,
            "category": category,
            "channel": channel,
            "received_at_utc": received_at_utc,
            "summary": summary,
        },
        overrides,
    )


def acknowledge_payload(
    acknowledged_at_utc: str = "2026-08-06T10:00:00Z", **overrides
) -> Dict[str, Any]:
    return _merge({"acknowledged_at_utc": acknowledged_at_utc}, overrides)


def request_info_payload(
    requested_at_utc: str = "2026-08-07T11:00:00Z",
    info_request_note: str = "Please send the card statement.",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {"info_request_note": info_request_note, "requested_at_utc": requested_at_utc},
        overrides,
    )


def answer_payload(
    answered_at_utc: str = "2026-08-07T11:00:00Z",
    disposition: str = "POLICY_EXPLAINED",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {"disposition": disposition, "answered_at_utc": answered_at_utc}, overrides
    )


def reopen_payload(
    reopened_at_utc: str,
    reopen_reason: str = "Passenger wrote back.",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {"reopened_at_utc": reopened_at_utc, "reopen_reason": reopen_reason}, overrides
    )


# ─── Regulator reports and the sweep (PRD §3.9) ───────


def report_payload(
    policy_profile_id: str,
    expected_policy_profile_version: int,
    period_start_utc: str = "2026-07-01T00:00:00Z",
    period_end_utc: str = "2026-07-31T23:59:59Z",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "policy_profile_id": policy_profile_id,
            "period_start_utc": period_start_utc,
            "period_end_utc": period_end_utc,
            "expected_policy_profile_version": expected_policy_profile_version,
        },
        overrides,
    )


def submit_report_payload(submitted_at_utc: str, **overrides) -> Dict[str, Any]:
    return _merge({"submitted_at_utc": submitted_at_utc}, overrides)


def amend_report_payload(
    amended_at_utc: str,
    amendment_reason: str = "Complaint reclassified after audit.",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {"amended_at_utc": amended_at_utc, "amendment_reason": amendment_reason},
        overrides,
    )


def sweep_payload(policy_profile_id: str, **overrides) -> Dict[str, Any]:
    return _merge({"policy_profile_id": policy_profile_id}, overrides)
