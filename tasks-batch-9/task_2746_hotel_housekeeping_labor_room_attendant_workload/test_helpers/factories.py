"""Request payload builders.

Every builder returns a plain `dict` whose numeric fields are real JSON numbers
(never strings) and accepts `**overrides` so a test can vary one field without
restating the rest.  Field names and permitted ranges come from PRD 3.
"""

from __future__ import annotations

from typing import Any, Optional

from .constants import (
    CATEGORY_STANDARD,
    DEFAULT_BUSINESS_DATE,
    LINEN_SHEET_SET,
    OCCUPANCY_VACANT,
    ORDINANCE_SQFT_CAP_2200,
    PROGRAM_OPT_OUT,
    PROOF_PHOTO_ID,
    SERVICE_CHECKOUT,
    WAIVER_DECISION_GRANT,
)

JsonDict = dict[str, Any]


def _merge(base: JsonDict, overrides: JsonDict) -> JsonDict:
    """Apply overrides; an override value of `None` deletes the field."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    """Sentinel: passing `OMIT` for a field removes it from the payload."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


_OMIT = _Omit()
OMIT = _OMIT


# --------------------------------------------------------------------------
# Property (PRD 3.1)
# --------------------------------------------------------------------------


def property_payload(**overrides: Any) -> JsonDict:
    """The canonical property: SQFT_CAP_2200 regime on the specification defaults."""
    return _merge(
        {
            "name": "Harborview Hotel",
            "ordinance_profile": ORDINANCE_SQFT_CAP_2200,
            "credit_minute_value": 30,
            "standard_shift_minutes": 480,
            "pre_post_shift_minutes": 45,
            "min_daily_paid_minutes": 240,
            "max_daily_credits": 16.00,
            "max_daily_square_feet": 2200,
            "laundry_sla_minutes": 240,
            "laundry_capacity_sets": 300,
            "reclean_threshold_score": 85.0,
            "inspection_sample_rate": 0.20,
            "probation_sample_rate": 0.50,
            "rest_buffer_minutes": 10,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Room types (PRD 3.1)
# --------------------------------------------------------------------------


def room_type_payload(property_id: str, **overrides: Any) -> JsonDict:
    """A standard king room type."""
    return _merge(
        {
            "property_id": property_id,
            "code": "KING",
            "square_feet": 420,
            "checkout_credits": 1.00,
            "stayover_credits": 0.50,
            "deep_clean_credits": 2.00,
            "linen_sets_per_room": 2,
        },
        overrides,
    )


def suite_room_type_payload(property_id: str, **overrides: Any) -> JsonDict:
    """A suite room type whose deep-clean value exceeds the 3.00 credit ceiling."""
    return _merge(
        {
            "property_id": property_id,
            "code": "SUITE",
            "square_feet": 780,
            "checkout_credits": 2.00,
            "stayover_credits": 1.00,
            "deep_clean_credits": 3.50,
            "linen_sets_per_room": 3,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Rooms (PRD 3.1)
# --------------------------------------------------------------------------


def room_payload(property_id: str, room_type_id: str, room_number: str, **overrides: Any) -> JsonDict:
    return _merge(
        {
            "property_id": property_id,
            "room_type_id": room_type_id,
            "room_number": room_number,
            "floor": 1,
            "occupancy_state": OCCUPANCY_VACANT,
        },
        overrides,
    )


def room_patch_payload(**overrides: Any) -> JsonDict:
    return dict(overrides)


# --------------------------------------------------------------------------
# Attendants (PRD 3.1)
# --------------------------------------------------------------------------


def attendant_payload(property_id: str, **overrides: Any) -> JsonDict:
    """A rank-and-file room attendant who may not inspect."""
    return _merge(
        {
            "property_id": property_id,
            "employee_code": "E-101",
            "full_name": "Rosa Diaz",
            "seniority_date": "2019-04-01",
            "hourly_rate_cents": 3000,
            "can_inspect": False,
            "restricted_duty": False,
        },
        overrides,
    )


def inspector_payload(property_id: str, **overrides: Any) -> JsonDict:
    """A credentialed working supervisor: `can_inspect` true."""
    return _merge(
        {
            "property_id": property_id,
            "employee_code": "E-900",
            "full_name": "Ivan Petrov",
            "seniority_date": "2014-02-01",
            "hourly_rate_cents": 4200,
            "can_inspect": True,
            "restricted_duty": False,
        },
        overrides,
    )


def attendant_patch_payload(**overrides: Any) -> JsonDict:
    return dict(overrides)


# --------------------------------------------------------------------------
# Forecast days (PRD 3.2)
# --------------------------------------------------------------------------


def forecast_day_payload(property_id: str, **overrides: Any) -> JsonDict:
    return _merge(
        {
            "property_id": property_id,
            "business_date": DEFAULT_BUSINESS_DATE,
            "forecast_occupied_rooms": 4,
            "forecast_arrivals": 1,
            "forecast_departures": 2,
            "planned_deep_clean_rooms": 1,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Shift rosters (PRD 3.3, 3.7)
# --------------------------------------------------------------------------


def shift_roster_payload(forecast_day_id: str, attendant_id: str, **overrides: Any) -> JsonDict:
    return _merge(
        {"forecast_day_id": forecast_day_id, "attendant_id": attendant_id},
        overrides,
    )


def roster_close_payload(worked_minutes: int, break_minutes: int, **overrides: Any) -> JsonDict:
    return _merge(
        {"worked_minutes": worked_minutes, "break_minutes": break_minutes},
        overrides,
    )


def waiver_request_payload(waiver_requested_credits: float, **overrides: Any) -> JsonDict:
    return _merge({"waiver_requested_credits": waiver_requested_credits}, overrides)


def waiver_decision_payload(decision: str = WAIVER_DECISION_GRANT, **overrides: Any) -> JsonDict:
    return _merge({"decision": decision}, overrides)


# --------------------------------------------------------------------------
# Room assignments (PRD 3.4, 3.5)
# --------------------------------------------------------------------------


def assignment_payload(
    roster_id: str,
    room_id: str,
    expected_roster_version: int,
    service_type: str = SERVICE_CHECKOUT,
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {
            "roster_id": roster_id,
            "room_id": room_id,
            "service_type": service_type,
            "expected_roster_version": expected_roster_version,
        },
        overrides,
    )


def start_payload(started_at: Optional[str] = None, **overrides: Any) -> JsonDict:
    base: JsonDict = {}
    if started_at is not None:
        base["started_at"] = started_at
    return _merge(base, overrides)


def complete_payload(completed_at: Optional[str] = None, **overrides: Any) -> JsonDict:
    base: JsonDict = {}
    if completed_at is not None:
        base["completed_at"] = completed_at
    return _merge(base, overrides)


# --------------------------------------------------------------------------
# Inspections (PRD 3.6)
# --------------------------------------------------------------------------


def inspection_payload(
    assignment_id: str,
    bathroom_points: int = 9,
    linen_points: int = 8,
    dust_points: int = 8,
    amenity_points: int = 8,
    floor_points: int = 10,
    **overrides: Any,
) -> JsonDict:
    """Default item scores 9/8/8/8/10 score exactly 85.0 and pass at the boundary."""
    return _merge(
        {
            "assignment_id": assignment_id,
            "bathroom_points": bathroom_points,
            "linen_points": linen_points,
            "dust_points": dust_points,
            "amenity_points": amenity_points,
            "floor_points": floor_points,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Linen and laundry (PRD 3.8)
# --------------------------------------------------------------------------


def linen_item_payload(property_id: str, **overrides: Any) -> JsonDict:
    return _merge(
        {
            "property_id": property_id,
            "linen_type": LINEN_SHEET_SET,
            "total_owned_sets": 40,
            "initial_soiled_sets": 0,
        },
        overrides,
    )


def soil_payload(sets: int, **overrides: Any) -> JsonDict:
    return _merge({"sets": sets}, overrides)


def laundry_cycle_payload(
    linen_item_id: str,
    batch_sets: int,
    dispatched_at: str,
    expected_return_at: str,
    expected_linen_item_version: int,
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {
            "linen_item_id": linen_item_id,
            "batch_sets": batch_sets,
            "dispatched_at": dispatched_at,
            "expected_return_at": expected_return_at,
            "expected_linen_item_version": expected_linen_item_version,
        },
        overrides,
    )


def laundry_return_payload(
    returned_at: Optional[str] = None,
    returned_sets: Optional[int] = None,
    **overrides: Any,
) -> JsonDict:
    base: JsonDict = {}
    if returned_at is not None:
        base["returned_at"] = returned_at
    if returned_sets is not None:
        base["returned_sets"] = returned_sets
    return _merge(base, overrides)


# --------------------------------------------------------------------------
# Lost and found (PRD 3.9)
# --------------------------------------------------------------------------


def lost_found_payload(
    property_id: str,
    room_id: str,
    found_by_attendant_id: str,
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {
            "property_id": property_id,
            "room_id": room_id,
            "found_by_attendant_id": found_by_attendant_id,
            "description": "Blue canvas tote bag left in the closet",
            "category": CATEGORY_STANDARD,
        },
        overrides,
    )


def store_payload(storage_bin: str = "B-12", **overrides: Any) -> JsonDict:
    return _merge({"storage_bin": storage_bin}, overrides)


def claim_payload(
    claimant_name: str = "Dana Kim",
    claimant_contact: str = "dana.kim@example.com",
    proof_kind: str = PROOF_PHOTO_ID,
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {
            "claimant_name": claimant_name,
            "claimant_contact": claimant_contact,
            "proof_kind": proof_kind,
        },
        overrides,
    )


def claim_decision_payload(decision: str, **overrides: Any) -> JsonDict:
    return _merge({"decision": decision}, overrides)


def dispose_payload(disposition: str, **overrides: Any) -> JsonDict:
    return _merge({"disposition": disposition}, overrides)


# --------------------------------------------------------------------------
# Service enrollments (PRD 3.9)
# --------------------------------------------------------------------------


def enrollment_payload(
    room_id: str,
    program: str = PROGRAM_OPT_OUT,
    nights: int = 2,
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {
            "room_id": room_id,
            "reservation_code": "RSV-70001",
            "program": program,
            "nights": nights,
        },
        overrides,
    )
