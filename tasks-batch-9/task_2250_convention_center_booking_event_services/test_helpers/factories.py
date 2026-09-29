"""Payload builders and small date/money helpers.

Each ``*_payload`` builder returns a valid request body for the corresponding
create endpoint; keyword overrides replace individual fields, and passing
``None`` for an optional field simply leaves the field out.
"""

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional

from .constants import (
    BALLROOM_B,
    CONSUMER_SHOW_WINDOW,
    CITYWIDE_WINDOW,
    LOCAL_EVENT_WINDOW,
    SUNBELT_PROMOTER,
    SEIU_LOCAL_3,
    SPARKLECLEAN_EXCLUSIVE,
)

# --------------------------------------------------------------------------
# Date and time helpers
# --------------------------------------------------------------------------


def iso_utc(day: str, hour: int = 0, minute: int = 0, second: int = 0) -> str:
    """Build a UTC instant string from a calendar day and a wall clock time."""
    return f"{day}T{hour:02d}:{minute:02d}:{second:02d}Z"


def parse_day(day: str) -> date:
    return datetime.strptime(day, "%Y-%m-%d").date()


def day_string(value: date) -> str:
    return value.isoformat()


def shift_days(day: str, delta: int) -> str:
    """Return the calendar day ``delta`` days away from ``day``."""
    return day_string(parse_day(day) + timedelta(days=delta))


def day_span_inclusive(first_day: str, last_day: str) -> int:
    """Number of calendar days in the closed interval ``[first_day, last_day]``."""
    return (parse_day(last_day) - parse_day(first_day)).days + 1


def days_between(first_day: str, last_day: str) -> int:
    """Whole days separating two calendar days (negative when reversed)."""
    return (parse_day(last_day) - parse_day(first_day)).days


def round_half_up(value: float) -> int:
    """Round a money amount to whole cents, halves away from zero."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Reference-data payloads
# --------------------------------------------------------------------------


def client_payload(**overrides: Any) -> Dict[str, Any]:
    payload = dict(SUNBELT_PROMOTER)
    payload.update(overrides)
    return payload


def space_payload(**overrides: Any) -> Dict[str, Any]:
    payload = dict(BALLROOM_B)
    payload.update(overrides)
    return payload


def child_space_payload(parent_space_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = dict(BALLROOM_B)
    payload["parent_space_id"] = parent_space_id
    payload.update(overrides)
    return payload


def policy_window_payload(event_class: str = "CONSUMER_SHOW", **overrides: Any) -> Dict[str, Any]:
    base = {
        "CONSUMER_SHOW": CONSUMER_SHOW_WINDOW,
        "LOCAL_EVENT": LOCAL_EVENT_WINDOW,
        "CITYWIDE_CONVENTION": CITYWIDE_WINDOW,
    }.get(event_class)
    payload: Dict[str, Any] = dict(base) if base is not None else {"event_class": event_class}
    payload.setdefault("priority_rank", 3)
    payload.setdefault("open_months_before", 18)
    payload.setdefault("close_months_before", 2)
    payload.setdefault("max_holds_per_booking", 2)
    payload.setdefault("challenge_response_hours", 48)
    payload.setdefault("rental_discount_pct", 0.0)
    payload.setdefault("max_challenge_rounds", 1)
    payload.update(overrides)
    return payload


def vendor_payload(**overrides: Any) -> Dict[str, Any]:
    payload = dict(SPARKLECLEAN_EXCLUSIVE)
    payload.update(overrides)
    return payload


def union_jurisdiction_payload(**overrides: Any) -> Dict[str, Any]:
    payload = dict(SEIU_LOCAL_3)
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Booking payloads
# --------------------------------------------------------------------------


def booking_payload(
    client_id: str,
    space_id: str,
    *,
    event_name: str = "Regional Gem Show",
    event_class: str = "CONSUMER_SHOW",
    move_in_start_date: str = "2027-03-01",
    show_start_date: str = "2027-03-02",
    show_end_date: str = "2027-03-04",
    move_out_end_date: str = "2027-03-05",
    projected_room_nights: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "space_id": space_id,
        "event_name": event_name,
        "event_class": event_class,
        "move_in_start_date": move_in_start_date,
        "show_start_date": show_start_date,
        "show_end_date": show_end_date,
        "move_out_end_date": move_out_end_date,
    }
    if projected_room_nights is not None:
        payload["projected_room_nights"] = projected_room_nights
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Event-service payloads
# --------------------------------------------------------------------------


def service_order_payload(
    vendor_id: str,
    service_category: str,
    ordered_quantity: float,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vendor_id": vendor_id,
        "service_category": service_category,
        "ordered_quantity": ordered_quantity,
    }
    payload.update(overrides)
    return payload


def labor_call_payload(
    jurisdiction_id: str,
    work_category: str,
    work_date: str,
    scheduled_start_hour: float,
    scheduled_end_hour: float,
    crew_size: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "jurisdiction_id": jurisdiction_id,
        "work_category": work_category,
        "work_date": work_date,
        "scheduled_start_hour": scheduled_start_hour,
        "scheduled_end_hour": scheduled_end_hour,
        "crew_size": crew_size,
    }
    payload.update(overrides)
    return payload


def catering_arrangement_payload(
    vendor_id: str,
    arrangement_type: str,
    estimated_fnb_cents: int,
    exception_reason: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vendor_id": vendor_id,
        "arrangement_type": arrangement_type,
        "estimated_fnb_cents": estimated_fnb_cents,
    }
    if exception_reason is not None:
        payload["exception_reason"] = exception_reason
    payload.update(overrides)
    return payload


def usage_record_payload(usage_date: str, usage_kind: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"usage_date": usage_date, "usage_kind": usage_kind}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Settlement payloads
# --------------------------------------------------------------------------


def settlement_line_item_payload(
    settlement_id: str,
    line_kind: str,
    amount_cents: int,
    source_ref_id: Optional[str] = None,
    memo: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "settlement_id": settlement_id,
        "line_kind": line_kind,
        "amount_cents": amount_cents,
    }
    if source_ref_id is not None:
        payload["source_ref_id"] = source_ref_id
    if memo is not None:
        payload["memo"] = memo
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Maintenance payloads
# --------------------------------------------------------------------------


def maintenance_blackout_payload(
    space_id: str,
    window_start_date: str,
    window_end_date: str,
    project_kind: str = "ROUTINE_MAINTENANCE",
    buffer_days: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "space_id": space_id,
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
        "project_kind": project_kind,
    }
    if buffer_days is not None:
        payload["buffer_days"] = buffer_days
    payload.update(overrides)
    return payload
