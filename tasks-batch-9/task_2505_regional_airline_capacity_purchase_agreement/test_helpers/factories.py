"""Request-payload builders.

Each builder returns a complete, valid payload for one write endpoint, with a
canonical rate card or schedule baked in so that a test only has to state the one
field its scenario cares about. Overrides are applied last, and passing ``None``
for a field is honoured (so a builder can be used to construct a payload that is
deliberately missing a value by popping the key afterwards).
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .types import JsonDict

# ---------------------------------------------------------------------------
# Canonical agreement rate card
# ---------------------------------------------------------------------------

AGREEMENT_DEFAULTS: Dict[str, Any] = {
    "mainline_partner_name": "Summit Air",
    "regional_carrier_name": "Cascade Regional",
    "fixed_monthly_fee_usd": 250000.00,
    "block_hour_rate_usd": 1450.75,
    "departure_rate_usd": 320.00,
    "aircraft_ownership_fee_usd": 62000.00,
    "incentive_pool_cap_usd": 90000.00,
    "penalty_cap_usd": 120000.00,
    "term_end_date": "2029-12-31",
}

# A second, deliberately different rate card for scenarios that need two
# agreements side by side.
SECOND_AGREEMENT_DEFAULTS: Dict[str, Any] = {
    "mainline_partner_name": "Beacon Airways",
    "regional_carrier_name": "Cascade Regional",
    "fixed_monthly_fee_usd": 180000.00,
    "block_hour_rate_usd": 1310.00,
    "departure_rate_usd": 295.00,
    "aircraft_ownership_fee_usd": 54000.00,
    "incentive_pool_cap_usd": 60000.00,
    "penalty_cap_usd": 80000.00,
    "term_end_date": "2030-06-30",
}


def _merge(base: JsonDict, overrides: JsonDict) -> JsonDict:
    payload = dict(base)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Schedule arithmetic
# ---------------------------------------------------------------------------

_INSTANT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def parse_instant(instant: str) -> datetime:
    """Read a UTC instant expressed with or without fractional seconds."""
    text = instant.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def format_instant(moment: datetime) -> str:
    """Render a UTC instant in the whole-second form the schedule uses."""
    return moment.astimezone(timezone.utc).strftime(_INSTANT_FORMAT)


def shift_instant(instant: str, *, minutes: int = 0, hours: int = 0, seconds: int = 0) -> str:
    """The instant obtained by moving ``instant`` forward by the given offset."""
    return format_instant(
        parse_instant(instant) + timedelta(minutes=minutes, hours=hours, seconds=seconds)
    )


def make_agreement_payload(**overrides: Any) -> JsonDict:
    """A registrable agreement with the canonical five money terms and term end."""
    return _merge(AGREEMENT_DEFAULTS, overrides)


def make_second_agreement_payload(**overrides: Any) -> JsonDict:
    """A second agreement whose rate card differs in every money field."""
    return _merge(SECOND_AGREEMENT_DEFAULTS, overrides)


# ---------------------------------------------------------------------------
# Crew bases and pilots
# ---------------------------------------------------------------------------


def make_crew_base_payload(
    agreement_id: str,
    station_code: str = "PDX",
    pilots_required_per_aircraft: int = 1,
    aircraft_allocation_cap: int = 2,
    **overrides: Any,
) -> JsonDict:
    """A crew base with its staffing ratio and fleet allocation cap."""
    return _merge(
        {
            "agreement_id": agreement_id,
            "station_code": station_code,
            "pilots_required_per_aircraft": pilots_required_per_aircraft,
            "aircraft_allocation_cap": aircraft_allocation_cap,
        },
        overrides,
    )


def make_pilot_payload(
    base_id: str,
    employee_ref: str = "EMP-0001",
    seat: str = "CAPTAIN",
    hire_class_date: str = "2026-07-01",
    **overrides: Any,
) -> JsonDict:
    """A pilot hired into a base's pipeline."""
    return _merge(
        {
            "base_id": base_id,
            "employee_ref": employee_ref,
            "seat": seat,
            "hire_class_date": hire_class_date,
        },
        overrides,
    )


def make_advance_payload(to_status: str, **overrides: Any) -> JsonDict:
    """A single training step, naming the destination status."""
    return _merge({"to_status": to_status}, overrides)


def make_attrite_payload(destination: str = "MAINLINE", **overrides: Any) -> JsonDict:
    """A pilot departure, naming where the pilot went."""
    return _merge({"destination": destination}, overrides)


# ---------------------------------------------------------------------------
# Aircraft
# ---------------------------------------------------------------------------


def make_aircraft_payload(
    agreement_id: str,
    assigned_base_id: str,
    tail_number: str = "N101CR",
    seat_count: int = 76,
    ownership: str = "REGIONAL_OWNED",
    **overrides: Any,
) -> JsonDict:
    """A tail registered against an agreement and a base."""
    return _merge(
        {
            "agreement_id": agreement_id,
            "assigned_base_id": assigned_base_id,
            "tail_number": tail_number,
            "seat_count": seat_count,
            "ownership": ownership,
        },
        overrides,
    )


def make_transition_payload(
    transition_reason: str = "FLEET_RENEWAL",
    target_ownership: str = "MAINLINE_OWNED",
    **overrides: Any,
) -> JsonDict:
    """The first step of a fleet renewal, naming why and what the tail becomes."""
    return _merge(
        {"transition_reason": transition_reason, "target_ownership": target_ownership},
        overrides,
    )


# ---------------------------------------------------------------------------
# Settlement months and flight legs
# ---------------------------------------------------------------------------


def make_schedule_cycle_payload(
    agreement_id: str,
    cycle_month: str = "2026-08",
    published_departures: int = 100,
    **overrides: Any,
) -> JsonDict:
    """A settlement month with the departure count it is buying."""
    return _merge(
        {
            "agreement_id": agreement_id,
            "cycle_month": cycle_month,
            "published_departures": published_departures,
        },
        overrides,
    )


def make_flight_leg_payload(
    cycle_id: str,
    aircraft_id: str,
    captain_pilot_id: str,
    flight_number: str = "SA1200",
    origin: str = "PDX",
    destination: str = "SEA",
    scheduled_departure_utc: str = "2026-08-05T14:00:00Z",
    scheduled_arrival_utc: str = "2026-08-05T15:30:00Z",
    planned_block_hours: float = 1.500,
    **overrides: Any,
) -> JsonDict:
    """A leg published against a month, a tail and a captain."""
    return _merge(
        {
            "cycle_id": cycle_id,
            "aircraft_id": aircraft_id,
            "captain_pilot_id": captain_pilot_id,
            "flight_number": flight_number,
            "origin": origin,
            "destination": destination,
            "scheduled_departure_utc": scheduled_departure_utc,
            "scheduled_arrival_utc": scheduled_arrival_utc,
            "planned_block_hours": planned_block_hours,
        },
        overrides,
    )


def make_completion_payload(
    actual_block_hours: float = 1.500,
    actual_arrival_utc: str = "2026-08-05T15:30:00Z",
    enplaned_bags: int = 1000,
    mishandled_bags: int = 2,
    **overrides: Any,
) -> JsonDict:
    """An operational report of a leg as flown."""
    return _merge(
        {
            "actual_block_hours": actual_block_hours,
            "actual_arrival_utc": actual_arrival_utc,
            "enplaned_bags": enplaned_bags,
            "mishandled_bags": mishandled_bags,
        },
        overrides,
    )


def make_cancel_payload(cause_code: str = "MAINTENANCE", **overrides: Any) -> JsonDict:
    """A cancellation report naming its cause."""
    return _merge({"cause_code": cause_code}, overrides)


# ---------------------------------------------------------------------------
# Cancellation claims
# ---------------------------------------------------------------------------


def make_classify_payload(classification: str = "UNCONTROLLABLE", **overrides: Any) -> JsonDict:
    """The mainline partner's stated verdict on a cancellation."""
    return _merge({"classification": classification}, overrides)


def make_dispute_payload(
    dispute_note: str = "Weather closed the field; not a crew failure.", **overrides: Any
) -> JsonDict:
    """The regional carrier's rationale for objecting to a verdict."""
    return _merge({"dispute_note": dispute_note}, overrides)


# ---------------------------------------------------------------------------
# Pass-through claims
# ---------------------------------------------------------------------------


def make_pass_through_payload(
    cycle_id: str,
    category: str = "FUEL",
    estimated_amount_usd: float = 40000.00,
    **overrides: Any,
) -> JsonDict:
    """A cost category opened against a month with its accrual estimate."""
    return _merge(
        {
            "cycle_id": cycle_id,
            "category": category,
            "estimated_amount_usd": estimated_amount_usd,
        },
        overrides,
    )


def make_submit_actual_payload(
    actual_amount_usd: float = 41000.00,
    supporting_doc_ref: str = "DOC-FUEL-0001",
    **overrides: Any,
) -> JsonDict:
    """The invoiced actual with its supporting document reference."""
    return _merge(
        {
            "actual_amount_usd": actual_amount_usd,
            "supporting_doc_ref": supporting_doc_ref,
        },
        overrides,
    )


def make_reconcile_payload(decision: str = "APPROVE", **overrides: Any) -> JsonDict:
    """An adjudication of a filed actual."""
    return _merge({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------


def make_invoice_payload(
    variant: str, expected_schedule_cycle_version: int, **overrides: Any
) -> JsonDict:
    """An invoice raised against a month, carrying the month's expected version."""
    return _merge(
        {
            "variant": variant,
            "expected_schedule_cycle_version": expected_schedule_cycle_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Brand audits
# ---------------------------------------------------------------------------


def make_brand_audit_payload(
    base_id: str,
    audit_scope: str = "UNIFORM",
    findings_count: int = 2,
    severity: str = "MAJOR",
    **overrides: Any,
) -> JsonDict:
    """A brand-standards audit raised against a base."""
    return _merge(
        {
            "base_id": base_id,
            "audit_scope": audit_scope,
            "findings_count": findings_count,
            "severity": severity,
        },
        overrides,
    )


def make_remediation_payload(
    to_remediation_status: str, evidence_ref: Optional[str] = None, **overrides: Any
) -> JsonDict:
    """A step along the remediation dimension, with evidence when required."""
    payload: JsonDict = {"to_remediation_status": to_remediation_status}
    if evidence_ref is not None:
        payload["evidence_ref"] = evidence_ref
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Extension negotiations
# ---------------------------------------------------------------------------


def make_extension_offer_payload(
    expected_agreement_version: int,
    proposed_term_end_date: str = "2031-12-31",
    proposed_block_hour_rate_usd: float = 1520.00,
    **overrides: Any,
) -> JsonDict:
    """A contract-extension offer carrying the agreement's expected version."""
    return _merge(
        {
            "proposed_term_end_date": proposed_term_end_date,
            "proposed_block_hour_rate_usd": proposed_block_hour_rate_usd,
            "expected_agreement_version": expected_agreement_version,
        },
        overrides,
    )


def make_revise_offer_payload(
    proposed_term_end_date: str = "2032-03-31",
    proposed_block_hour_rate_usd: float = 1525.00,
    **overrides: Any,
) -> JsonDict:
    """The mainline's revised offer, which carries no expected version of its own."""
    return _merge(
        {
            "proposed_term_end_date": proposed_term_end_date,
            "proposed_block_hour_rate_usd": proposed_block_hour_rate_usd,
        },
        overrides,
    )


def make_counter_payload(
    counter_term_end_date: str = "2032-06-30",
    counter_block_hour_rate_usd: float = 1600.00,
    **overrides: Any,
) -> JsonDict:
    """The regional carrier's counter term and rate."""
    return _merge(
        {
            "counter_term_end_date": counter_term_end_date,
            "counter_block_hour_rate_usd": counter_block_hour_rate_usd,
        },
        overrides,
    )


def make_terminate_payload(
    termination_reason: str = "Network restructuring", **overrides: Any
) -> JsonDict:
    """A deliberate wind-down with its recorded reason."""
    return _merge({"termination_reason": termination_reason}, overrides)


__all__ = [
    "parse_instant",
    "format_instant",
    "shift_instant",
    "AGREEMENT_DEFAULTS",
    "SECOND_AGREEMENT_DEFAULTS",
    "make_agreement_payload",
    "make_second_agreement_payload",
    "make_crew_base_payload",
    "make_pilot_payload",
    "make_advance_payload",
    "make_attrite_payload",
    "make_aircraft_payload",
    "make_transition_payload",
    "make_schedule_cycle_payload",
    "make_flight_leg_payload",
    "make_completion_payload",
    "make_cancel_payload",
    "make_classify_payload",
    "make_dispute_payload",
    "make_pass_through_payload",
    "make_submit_actual_payload",
    "make_reconcile_payload",
    "make_invoice_payload",
    "make_brand_audit_payload",
    "make_remediation_payload",
    "make_extension_offer_payload",
    "make_revise_offer_payload",
    "make_counter_payload",
    "make_terminate_payload",
]
