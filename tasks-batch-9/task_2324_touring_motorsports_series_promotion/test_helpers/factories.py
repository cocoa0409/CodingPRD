"""Payload factories.

Each factory builds only the client-supplied fields of its endpoint, fills them
with defaults that satisfy the documented validation rules, and accepts keyword
overrides. Passing ``None`` for an optional field removes it from the payload so
that server-side defaulting can be exercised.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from . import constants as C


def _drop_none(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Remove keys whose value is ``None`` so the field is simply absent."""
    return {key: value for key, value in payload.items() if value is not None}


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, then drop any key explicitly set to ``None``."""
    payload.update(overrides)
    return _drop_none(payload)


# ---------------------------------------------------------------------------
# Season
# ---------------------------------------------------------------------------


def make_season_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for creating a season."""
    payload: Dict[str, Any] = {
        "name": C.DEFAULT_SEASON_NAME,
        "year": C.DEFAULT_SEASON_YEAR,
        "season_start_date": C.DEFAULT_SEASON_START_DATE,
        "season_end_date": C.DEFAULT_SEASON_END_DATE,
        "total_marketing_budget_cents": C.DEFAULT_SEASON_MARKETING_BUDGET_CENTS,
        "market_rotation_cooldown_days": C.DEFAULT_MARKET_ROTATION_COOLDOWN_DAYS,
    }
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Venue
# ---------------------------------------------------------------------------


def make_venue_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for registering a building."""
    payload: Dict[str, Any] = {
        "name": C.DEFAULT_VENUE_NAME,
        "market_code": C.DEFAULT_VENUE_MARKET_CODE,
        "city": C.DEFAULT_VENUE_CITY,
        "state_code": C.DEFAULT_VENUE_STATE_CODE,
        "seat_capacity": C.DEFAULT_VENUE_SEAT_CAPACITY,
        "floor_type": C.DEFAULT_VENUE_FLOOR_TYPE,
        "catch_fence_max_height_ft": C.DEFAULT_VENUE_CATCH_FENCE_MAX_HEIGHT_FT,
        "medical_bay_count": C.DEFAULT_VENUE_MEDICAL_BAY_COUNT,
        "load_in_hours_required": C.DEFAULT_VENUE_LOAD_IN_HOURS_REQUIRED,
        "staging_bay_count": C.DEFAULT_VENUE_STAGING_BAY_COUNT,
        "turnaround_hours": C.DEFAULT_VENUE_TURNAROUND_HOURS,
    }
    return _merge(payload, overrides)


def make_second_venue_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for a building in a second market, for multi-stop scenarios."""
    payload = make_venue_payload(
        name=C.SECOND_VENUE_NAME,
        market_code=C.SECOND_VENUE_MARKET_CODE,
        city=C.SECOND_VENUE_CITY,
        state_code=C.SECOND_VENUE_STATE_CODE,
    )
    return _merge(payload, overrides)


def make_third_venue_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for a building in a third market, for multi-stop scenarios."""
    payload = make_venue_payload(
        name=C.THIRD_VENUE_NAME,
        market_code=C.THIRD_VENUE_MARKET_CODE,
        city=C.THIRD_VENUE_CITY,
        state_code=C.THIRD_VENUE_STATE_CODE,
    )
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Venue booking
# ---------------------------------------------------------------------------


def make_venue_booking_payload(
    season_id: str, venue_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Body for proposing rental terms for a date at a venue."""
    payload: Dict[str, Any] = {
        "season_id": season_id,
        "venue_id": venue_id,
        "tour_date": C.DEFAULT_TOUR_DATE,
        "rental_base_cents": C.DEFAULT_RENTAL_BASE_CENTS,
        "revenue_share_pct": C.DEFAULT_REVENUE_SHARE_PCT,
        "per_ticket_facility_fee_cents": C.DEFAULT_PER_TICKET_FACILITY_FEE_CENTS,
        "load_in_start_utc": C.DEFAULT_LOAD_IN_START_UTC,
        "tear_down_end_utc": C.DEFAULT_TEAR_DOWN_END_UTC,
    }
    return _merge(payload, overrides)


def make_counter_terms_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for a venue counter-offer on a booking."""
    payload: Dict[str, Any] = {
        "rental_base_cents": 3300000,
        "revenue_share_pct": 0.14,
        "per_ticket_facility_fee_cents": 400,
        "note": "Building counters the promoter's terms.",
    }
    return _merge(payload, overrides)


def make_revise_terms_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for a promoter revision of the terms after a counter."""
    payload: Dict[str, Any] = {
        "rental_base_cents": 3150000,
        "revenue_share_pct": 0.13,
        "per_ticket_facility_fee_cents": 375,
        "note": "Promoter re-proposes.",
    }
    return _merge(payload, overrides)


def make_withdraw_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for withdrawing a booking."""
    payload: Dict[str, Any] = {"reason": "Routing change for the tour."}
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Tour stop logistics
# ---------------------------------------------------------------------------


def make_logistics_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for setting show timing and pit party terms on a stop."""
    payload: Dict[str, Any] = {
        "doors_open_utc": C.DEFAULT_DOORS_OPEN_UTC,
        "show_start_utc": C.DEFAULT_SHOW_START_UTC,
        "show_window_minutes": C.DEFAULT_SHOW_WINDOW_MINUTES,
        "pit_party_price_cents": C.DEFAULT_PIT_PARTY_PRICE_CENTS,
        "pit_party_capacity": C.DEFAULT_PIT_PARTY_CAPACITY,
    }
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Competitor and vehicle entry
# ---------------------------------------------------------------------------


def make_competitor_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for registering a competing team."""
    payload: Dict[str, Any] = {
        "team_name": C.DEFAULT_TEAM_NAME,
        "driver_name": C.DEFAULT_DRIVER_NAME,
        "home_market_code": C.DEFAULT_HOME_MARKET_CODE,
        "vehicle_class": C.DEFAULT_VEHICLE_CLASS,
    }
    return _merge(payload, overrides)


def make_vehicle_entry_payload(
    competitor_id: str, tour_stop_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Body for entering a vehicle in a stop."""
    payload: Dict[str, Any] = {
        "competitor_id": competitor_id,
        "tour_stop_id": tour_stop_id,
        "vehicle_number": C.DEFAULT_VEHICLE_NUMBER,
        "vehicle_weight_lbs": C.DEFAULT_VEHICLE_WEIGHT_LBS,
        "haul_distance_miles": C.DEFAULT_HAUL_DISTANCE_MILES,
        "scheduled_arrival_utc": C.DEFAULT_SCHEDULED_ARRIVAL_UTC,
    }
    return _merge(payload, overrides)


def make_check_in_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for recording the transporter's arrival."""
    payload: Dict[str, Any] = {"arrival_note": "Transporter staged in its bay."}
    return _merge(payload, overrides)


def make_tech_inspection_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for filing one technical inspection attempt."""
    payload: Dict[str, Any] = {
        "result": "PASSED",
        "defect_severity": "NONE",
        "notes": "Nothing found on the attempt.",
    }
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Show segment
# ---------------------------------------------------------------------------


def make_show_segment_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for inserting a run-order segment."""
    payload: Dict[str, Any] = {
        "segment_type": "COMPETITION",
        "title": "Heat 1",
        "run_order_position": 1,
        "duration_minutes": 30,
    }
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Ticket tier and order
# ---------------------------------------------------------------------------


def make_ticket_tier_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for adding a pricing tier to a stop."""
    payload: Dict[str, Any] = {
        "tier_code": C.DEFAULT_TIER_CODE,
        "price_cents": C.DEFAULT_TIER_PRICE_CENTS,
        "allotment": C.DEFAULT_TIER_ALLOTMENT,
        "on_sale_start_utc": C.DEFAULT_ON_SALE_START_UTC,
        "on_sale_end_utc": C.DEFAULT_ON_SALE_END_UTC,
        "group_min_qty": C.DEFAULT_GROUP_MIN_QTY,
        "group_discount_pct": C.DEFAULT_GROUP_DISCOUNT_PCT,
    }
    return _merge(payload, overrides)


def make_second_ticket_tier_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for a second, cheaper pricing tier on the same stop."""
    payload = make_ticket_tier_payload(
        tier_code=C.DEFAULT_SECOND_TIER_CODE,
        price_cents=C.DEFAULT_SECOND_TIER_PRICE_CENTS,
        allotment=C.DEFAULT_SECOND_TIER_ALLOTMENT,
    )
    return _merge(payload, overrides)


def make_ticket_order_payload(
    tour_stop_id: str,
    ticket_tier_id: str,
    expected_ticket_tier_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for placing an order against a tier.

    ``expected_ticket_tier_version`` is mandatory on this endpoint: it must be
    the tier's current ``version``, read immediately before the call.
    """
    payload: Dict[str, Any] = {
        "tour_stop_id": tour_stop_id,
        "ticket_tier_id": ticket_tier_id,
        "purchaser_name": C.DEFAULT_PURCHASER_NAME,
        "purchaser_email": C.DEFAULT_PURCHASER_EMAIL,
        "qty": C.DEFAULT_ORDER_QTY,
        "expected_ticket_tier_version": expected_ticket_tier_version,
    }
    return _merge(payload, overrides)


def make_refund_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for refunding a paid order."""
    payload: Dict[str, Any] = {"reason": "Purchaser requested a refund."}
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Sponsor and activation
# ---------------------------------------------------------------------------


def make_sponsor_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for registering a sponsor."""
    payload: Dict[str, Any] = {
        "company_name": C.DEFAULT_SPONSOR_COMPANY_NAME,
        "category": C.DEFAULT_SPONSOR_CATEGORY,
        "contact_email": C.DEFAULT_SPONSOR_CONTACT_EMAIL,
        "exclusive_category": True,
    }
    return _merge(payload, overrides)


def make_sponsorship_activation_payload(
    sponsor_id: str,
    tour_stop_id: str,
    hospitality_tier_id: Optional[str] = None,
    branded_vehicle_entry_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for proposing an activation package.

    Hospitality seats are only meaningful alongside a hospitality tier, so the
    seat count is omitted when no tier is supplied.
    """
    payload: Dict[str, Any] = {
        "sponsor_id": sponsor_id,
        "tour_stop_id": tour_stop_id,
        "fee_cents": C.DEFAULT_ACTIVATION_FEE_CENTS,
        "vehicle_branding_slots": (
            C.DEFAULT_VEHICLE_BRANDING_SLOTS if branded_vehicle_entry_id else 0
        ),
        "signage_units": C.DEFAULT_SIGNAGE_UNITS,
    }
    if hospitality_tier_id is not None:
        payload["hospitality_tier_id"] = hospitality_tier_id
        payload["hospitality_seat_count"] = C.DEFAULT_HOSPITALITY_SEAT_COUNT
    if branded_vehicle_entry_id is not None:
        payload["branded_vehicle_entry_id"] = branded_vehicle_entry_id
    return _merge(payload, overrides)


def make_fulfill_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for signing off an activation's obligations."""
    payload: Dict[str, Any] = {"note": "Signage and branding delivered."}
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Safety plan
# ---------------------------------------------------------------------------


def make_safety_plan_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for creating a stop's safety plan."""
    payload: Dict[str, Any] = {
        "barrier_linear_feet": C.DEFAULT_BARRIER_LINEAR_FEET,
        "catch_fence_height_ft": C.DEFAULT_CATCH_FENCE_HEIGHT_FT,
        "medical_als_staff_count": C.DEFAULT_ALS_STAFF_COUNT,
        "medical_bls_staff_count": C.DEFAULT_BLS_STAFF_COUNT,
        "ambulance_count": C.DEFAULT_AMBULANCE_COUNT,
        "emergency_access_lanes": C.DEFAULT_EMERGENCY_ACCESS_LANES,
    }
    return _merge(payload, overrides)


def make_safety_plan_update_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for revising a plan's provisioning; every field is optional."""
    return _drop_none(dict(overrides))


def make_certify_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for certifying a submitted plan."""
    payload: Dict[str, Any] = {"note": "Provisioning verified on site."}
    return _merge(payload, overrides)


def make_return_plan_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for returning a submitted plan for rework."""
    payload: Dict[str, Any] = {"reason": "Barrier run needs extending."}
    return _merge(payload, overrides)


def make_safety_suspend_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for suspending a stop on safety grounds."""
    payload: Dict[str, Any] = {"reason": "Floor conditions unsafe."}
    return _merge(payload, overrides)


def make_safety_reinstate_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for lifting a safety suspension."""
    payload: Dict[str, Any] = {"note": "Floor re-graded and cleared."}
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Marketing allocation
# ---------------------------------------------------------------------------


def make_marketing_allocation_payload(
    expected_season_version: int, **overrides: Any
) -> Dict[str, Any]:
    """Body for committing local marketing spend on one channel.

    ``expected_season_version`` is mandatory on this endpoint: it must be the
    season's current ``version``, read immediately before the call.
    """
    payload: Dict[str, Any] = {
        "channel": C.DEFAULT_MARKETING_CHANNEL,
        "amount_cents": C.DEFAULT_MARKETING_AMOUNT_CENTS,
        "expected_season_version": expected_season_version,
    }
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------


def make_approve_settlement_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for approving a settlement under the final variant."""
    payload: Dict[str, Any] = {"note": "Reconciled against the box office."}
    return _merge(payload, overrides)


def make_dispute_settlement_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for disputing a prepared settlement."""
    payload: Dict[str, Any] = {"dispute_reason": "Facility fee count disagrees."}
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def make_clock_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for setting the logical clock."""
    payload: Dict[str, Any] = {"to_iso8601": C.CLOCK_DEFAULT_UTC}
    return _merge(payload, overrides)
