"""Payload factories.

Each factory returns the canonical, valid request body for one endpoint and
accepts keyword overrides so a test can perturb exactly the one field it cares
about. The canonical values are the ones the pricing arithmetic in the tests is
built around, so overriding a money-bearing field will move the expected
totals.
"""

from typing import Any, Dict, List, Optional

from .constants import ALL_VEHICLE_CLASSES, DEFAULT_CLOCK_UTC
from .types import (
    CauseCode,
    CheckType,
    DeliveryOption,
    DocType,
    PhotoPhase,
    PlanTier,
    PolicyTier,
    QualificationResult,
    ReadingType,
    SeasonCode,
    VehicleClass,
    Zone,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def clock_payload(to_iso8601: str = DEFAULT_CLOCK_UTC) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


# ---------------------------------------------------------------------------
# Owner / Renter
# ---------------------------------------------------------------------------
def owner_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "display_name": "Ada Rigby",
            "email": "ada@rvshare.test",
            "payout_state_code": "OR",
        },
        overrides,
    )


def renter_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "display_name": "Ben Traveler",
            "email": "ben@rvshare.test",
            "date_of_birth": "1994-05-10",
            "license_state_code": "OR",
        },
        overrides,
    )


def penalty_adjustment_payload(points_delta: int, reason: str) -> Dict[str, Any]:
    return {"points_delta": points_delta, "reason": reason}


def wallet_adjustment_payload(
    amount_cents_delta: int, reason: str = "initial wallet top-up"
) -> Dict[str, Any]:
    return {"amount_cents_delta": amount_cents_delta, "reason": reason}


# ---------------------------------------------------------------------------
# Renter qualifications
# ---------------------------------------------------------------------------
def driving_record_check_payload(
    renter_id: str,
    result: str = QualificationResult.CLEAR,
    violation_points: int = 2,
    checked_at: str = "2026-07-01T00:00:00Z",
    expires_on: Optional[str] = "2027-07-01",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "renter_id": renter_id,
            "check_type": CheckType.DRIVING_RECORD,
            "result": result,
            "violation_points": violation_points,
            "checked_at": checked_at,
            "expires_on": expires_on,
        },
        overrides,
    )


def towing_experience_check_payload(
    renter_id: str,
    result: str = QualificationResult.VERIFIED_BASIC,
    checked_at: str = "2026-07-01T00:00:00Z",
    expires_on: Optional[str] = "2027-07-01",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "renter_id": renter_id,
            "check_type": CheckType.TOWING_EXPERIENCE,
            "result": result,
            "violation_points": 0,
            "checked_at": checked_at,
            "expires_on": expires_on,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Configuration rows
# ---------------------------------------------------------------------------
def protection_plan_payload(**overrides: Any) -> Dict[str, Any]:
    """The canonical STANDARD plan the pricing walkthroughs are built on."""
    return _merge(
        {
            "tier": PlanTier.STANDARD,
            "daily_premium_cents": 4900,
            "premium_pct_of_base_bp": 1800,
            "deductible_cents": 150000,
            "coverage_ceiling_cents": 3000000,
            "excluded_causes": [CauseCode.AWNING_WIND],
            "eligible_vehicle_classes": list(ALL_VEHICLE_CLASSES),
        },
        overrides,
    )


def cancellation_policy_payload(**overrides: Any) -> Dict[str, Any]:
    """The canonical MODERATE policy."""
    return _merge(
        {
            "tier": PolicyTier.MODERATE,
            "full_refund_hours_before": 72,
            "partial_refund_pct_bp": 5000,
            "renter_cancel_penalty_points": 2,
            "owner_cancel_penalty_points": 6,
            "owner_cancel_fee_bp": 1000,
        },
        overrides,
    )


def pricing_season_payload(
    season_code: str, start_month_day: str, end_month_day: str, multiplier_bp: int
) -> Dict[str, Any]:
    return {
        "season_code": season_code,
        "start_month_day": start_month_day,
        "end_month_day": end_month_day,
        "multiplier_bp": multiplier_bp,
    }


def peak_season_payload() -> Dict[str, Any]:
    return pricing_season_payload(SeasonCode.PEAK, "06-01", "08-31", 13500)


def shoulder_season_payload() -> Dict[str, Any]:
    return pricing_season_payload(SeasonCode.SHOULDER, "09-01", "10-31", 11000)


def off_season_payload() -> Dict[str, Any]:
    return pricing_season_payload(SeasonCode.OFF, "01-01", "05-31", 8500)


def campground_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Cascade Bend RV Park",
            "state_code": "OR",
            "max_rig_length_ft": 40,
            "daily_dropoff_capacity": 1,
            "dropoff_buffer_minutes": 30,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Listings and documents
# ---------------------------------------------------------------------------
def listing_payload(owner_id: str, **overrides: Any) -> Dict[str, Any]:
    """The canonical towed travel trailer whose nightly rate drives the maths."""
    return _merge(
        {
            "owner_id": owner_id,
            "nickname": "Ponderosa 30BH",
            "vehicle_class": VehicleClass.TRAVEL_TRAILER,
            "gvwr_lbs": 8500,
            "length_ft": 30,
            "base_nightly_rate_cents": 21533,
            "included_miles_per_night": 100,
            "mileage_overage_rate_cents_per_mile": 65,
            "included_generator_hours_per_night": 3.0,
            "generator_overage_rate_cents_per_hour": 425,
            "min_renter_age": 25,
            "delivery_offered": True,
            "delivery_base_fee_cents": 12000,
            "delivery_per_mile_cents": 350,
        },
        overrides,
    )


def listing_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def listing_suspend_payload(
    suspend_reason: str = "roof seal recall pending",
) -> Dict[str, Any]:
    return {"suspend_reason": suspend_reason}


def vehicle_document_payload(
    listing_id: str,
    doc_type: str,
    image_ref: str,
    expected_listing_version: int,
    zone: Optional[str] = None,
    expires_on: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "listing_id": listing_id,
        "doc_type": doc_type,
        "image_ref": image_ref,
        "expected_listing_version": expected_listing_version,
    }
    if zone is not None:
        payload["zone"] = zone
    if expires_on is not None:
        payload["expires_on"] = expires_on
    return payload


def title_document_payload(
    listing_id: str, expected_listing_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        vehicle_document_payload(
            listing_id,
            DocType.TITLE,
            "s3://docs/title-1.pdf",
            expected_listing_version,
            expires_on="2028-01-01",
        ),
        overrides,
    )


def registration_document_payload(
    listing_id: str, expected_listing_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        vehicle_document_payload(
            listing_id,
            DocType.REGISTRATION,
            "s3://docs/reg-1.pdf",
            expected_listing_version,
            expires_on="2027-06-30",
        ),
        overrides,
    )


def insurance_document_payload(
    listing_id: str, expected_listing_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        vehicle_document_payload(
            listing_id,
            DocType.INSURANCE_POLICY,
            "s3://docs/ins-1.pdf",
            expected_listing_version,
            expires_on="2027-03-31",
        ),
        overrides,
    )


_INSPECTION_IMAGE_REFS = {
    Zone.EXTERIOR_FRONT: "s3://insp/front.jpg",
    Zone.EXTERIOR_REAR: "s3://insp/rear.jpg",
    Zone.INTERIOR: "s3://insp/interior.jpg",
    Zone.ROOF: "s3://insp/roof.jpg",
    Zone.UNDERCARRIAGE: "s3://insp/under.jpg",
}


def inspection_photo_payload(
    listing_id: str, zone: str, expected_listing_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        vehicle_document_payload(
            listing_id,
            DocType.INSPECTION_PHOTO,
            _INSPECTION_IMAGE_REFS[zone],
            expected_listing_version,
            zone=zone,
        ),
        overrides,
    )


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------
def booking_payload(
    listing_id: str,
    renter_id: str,
    protection_plan_id: str,
    cancellation_policy_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """The canonical four-night PICKUP booking, 2026-08-29 to 2026-09-02."""
    return _merge(
        {
            "listing_id": listing_id,
            "renter_id": renter_id,
            "protection_plan_id": protection_plan_id,
            "cancellation_policy_id": cancellation_policy_id,
            "start_date": "2026-08-29",
            "end_date": "2026-09-02",
            "delivery_option": DeliveryOption.PICKUP,
            "declared_miles": 380,
            "declared_generator_hours": 11.0,
        },
        overrides,
    )


def cancel_payload(cancel_reason: str) -> Dict[str, Any]:
    return {"cancel_reason": cancel_reason}


def reversal_payload(reversal_reason: str) -> Dict[str, Any]:
    return {"reversal_reason": reversal_reason}


# ---------------------------------------------------------------------------
# Delivery assignments
# ---------------------------------------------------------------------------
def delivery_assignment_payload(
    booking_id: str,
    campground_id: str,
    window_start: str,
    window_end: str,
    distance_miles: int,
    expected_booking_version: int,
    setup_fee_cents: Optional[int] = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "booking_id": booking_id,
        "campground_id": campground_id,
        "window_start": window_start,
        "window_end": window_end,
        "distance_miles": distance_miles,
        "expected_booking_version": expected_booking_version,
    }
    if setup_fee_cents is not None:
        payload["setup_fee_cents"] = setup_fee_cents
    return _merge(payload, overrides)


def void_payload(void_reason: str) -> Dict[str, Any]:
    return {"void_reason": void_reason}


# ---------------------------------------------------------------------------
# Meter readings and trip photos
# ---------------------------------------------------------------------------
def meter_reading_payload(
    booking_id: str,
    reading_type: str,
    odometer_miles: int,
    generator_hours: float,
    recorded_at: str,
) -> Dict[str, Any]:
    return {
        "booking_id": booking_id,
        "reading_type": reading_type,
        "odometer_miles": odometer_miles,
        "generator_hours": generator_hours,
        "recorded_at": recorded_at,
    }


def pre_trip_reading_payload(booking_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        meter_reading_payload(
            booking_id, ReadingType.PRE_TRIP, 42000, 120.0, "2026-08-29T15:00:00Z"
        ),
        overrides,
    )


def mid_trip_reading_payload(booking_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        meter_reading_payload(
            booking_id, ReadingType.MID_TRIP, 42260, 130.5, "2026-08-31T15:00:00Z"
        ),
        overrides,
    )


def post_trip_reading_payload(booking_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        meter_reading_payload(
            booking_id, ReadingType.POST_TRIP, 42400, 132.0, "2026-09-02T11:00:00Z"
        ),
        overrides,
    )


_TRIP_PHOTO_IMAGE_REFS = {
    (PhotoPhase.PRE_TRIP, Zone.EXTERIOR_FRONT): "s3://trip/pre-front.jpg",
    (PhotoPhase.PRE_TRIP, Zone.EXTERIOR_REAR): "s3://trip/pre-rear.jpg",
    (PhotoPhase.PRE_TRIP, Zone.INTERIOR): "s3://trip/pre-interior.jpg",
    (PhotoPhase.PRE_TRIP, Zone.ROOF): "s3://trip/pre-roof.jpg",
    (PhotoPhase.PRE_TRIP, Zone.UNDERCARRIAGE): "s3://trip/pre-under.jpg",
    (PhotoPhase.POST_TRIP, Zone.EXTERIOR_FRONT): "s3://trip/post-front.jpg",
    (PhotoPhase.POST_TRIP, Zone.EXTERIOR_REAR): "s3://trip/post-rear.jpg",
    (PhotoPhase.POST_TRIP, Zone.INTERIOR): "s3://trip/post-interior.jpg",
    (PhotoPhase.POST_TRIP, Zone.ROOF): "s3://trip/post-roof.jpg",
    (PhotoPhase.POST_TRIP, Zone.UNDERCARRIAGE): "s3://trip/post-under.jpg",
}


def trip_photo_payload(
    booking_id: str,
    phase: str,
    zone: str,
    damage_flagged: bool = False,
    image_ref: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "booking_id": booking_id,
        "phase": phase,
        "zone": zone,
        "damage_flagged": damage_flagged,
        "image_ref": image_ref or _TRIP_PHOTO_IMAGE_REFS[(phase, zone)],
    }


# ---------------------------------------------------------------------------
# Damage claims
# ---------------------------------------------------------------------------
def damage_claim_payload(
    booking_id: str,
    cause_code: str = CauseCode.COLLISION,
    damage_zone: str = Zone.EXTERIOR_REAR,
    claimed_amount_cents: int = 220000,
    description: str = "Rear cap cracked and tail light housing shattered.",
) -> Dict[str, Any]:
    return {
        "booking_id": booking_id,
        "cause_code": cause_code,
        "damage_zone": damage_zone,
        "claimed_amount_cents": claimed_amount_cents,
        "description": description,
    }


def info_request_payload(
    info_request_note: str = "Send the repair estimate from a certified shop.",
) -> Dict[str, Any]:
    return {"info_request_note": info_request_note}


def info_response_payload(response_note: str = "Estimate attached.") -> Dict[str, Any]:
    return {"response_note": response_note}


def adjudication_payload(
    override_amount_cents: Optional[int] = None,
    override_reason: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if override_amount_cents is not None:
        payload["override_amount_cents"] = override_amount_cents
    if override_reason is not None:
        payload["override_reason"] = override_reason
    return payload


def withdraw_payload(withdraw_reason: str) -> Dict[str, Any]:
    return {"withdraw_reason": withdraw_reason}


# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------
def page_params(
    limit: Optional[int] = None, offset: Optional[int] = None, **filters: Any
) -> Dict[str, Any]:
    params: Dict[str, Any] = dict(filters)
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    return params


def all_inspection_zones() -> List[str]:
    return [
        Zone.EXTERIOR_FRONT,
        Zone.EXTERIOR_REAR,
        Zone.INTERIOR,
        Zone.ROOF,
        Zone.UNDERCARRIAGE,
    ]
