"""Shape and invariant assertions for the RV share marketplace API.

The per-resource ``assert_*`` helpers check the field inventory and primitive
shapes the PRD publishes. The invariant helpers check the cross-resource
identities the PRD states must hold at all times.
"""

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import ALL_VEHICLE_CLASSES
from .types import (
    AssignmentStatus,
    CampgroundStatus,
    ClaimStatus,
    ComparisonVerdict,
    DeliveryOption,
    DocType,
    DocVerificationStatus,
    DrivingRecordStatus,
    InsuranceStatus,
    LedgerParty,
    ListingStatus,
    LoyaltyTier,
    OwnerStatus,
    PhotoPhase,
    PlanTier,
    PolicyTier,
    QualificationResult,
    ReadingType,
    SeasonCode,
    SettlementStatus,
    TowingTier,
    TripStatus,
    Zone,
)

_ISO_DATE_LEN = 10


# ---------------------------------------------------------------------------
# Generic shape helpers
# ---------------------------------------------------------------------------
def assert_identifier(value: Any, field: str = "id") -> None:
    assert isinstance(value, str) and value, f"{field} must be a non-empty string"
    assert is_valid_uuid(value), f"{field} must be a UUID, got {value!r}"


def assert_iso_date(value: Any, field: str) -> None:
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert len(value) == _ISO_DATE_LEN, f"{field} must be a YYYY-MM-DD date, got {value!r}"
    assert value[4] == "-" and value[7] == "-", f"{field} must be YYYY-MM-DD, got {value!r}"


def assert_utc_timestamp(value: Any, field: str) -> None:
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field} must be an ISO-8601 UTC instant, got {value!r}"


def assert_mutable_common_fields(resource: Dict[str, Any], label: str) -> None:
    """id, created_at, updated_at and version for a mutable resource."""
    assert_identifier(resource.get("id"), f"{label}.id")
    assert_utc_timestamp(resource.get("created_at"), f"{label}.created_at")
    assert_utc_timestamp(resource.get("updated_at"), f"{label}.updated_at")
    version = resource.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"{label}.version must be a positive integer, got {version!r}"
    )


def assert_append_only_common_fields(resource: Dict[str, Any], label: str) -> None:
    """Append-only evidence carries only id and created_at."""
    assert_identifier(resource.get("id"), f"{label}.id")
    assert_utc_timestamp(resource.get("created_at"), f"{label}.created_at")
    assert "updated_at" not in resource, f"{label} must not expose updated_at"
    assert "version" not in resource, f"{label} must not expose version"


def assert_enum(value: Any, allowed: Iterable[str], field: str) -> None:
    allowed = tuple(allowed)
    assert value in allowed, f"{field} must be one of {allowed}, got {value!r}"


def assert_non_negative_int(value: Any, field: str) -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer, got {value!r}"
    )
    assert value >= 0, f"{field} must not be negative, got {value}"


def assert_bool(value: Any, field: str) -> None:
    assert isinstance(value, bool), f"{field} must be a boolean, got {value!r}"


# ---------------------------------------------------------------------------
# Per-resource assertions
# ---------------------------------------------------------------------------
def assert_owner(owner: Dict[str, Any]) -> None:
    assert_mutable_common_fields(owner, "owner")
    assert isinstance(owner["display_name"], str) and owner["display_name"]
    assert isinstance(owner["email"], str) and owner["email"]
    assert isinstance(owner["payout_state_code"], str) and owner["payout_state_code"]
    assert_enum(owner["status"], (OwnerStatus.ACTIVE, OwnerStatus.SUSPENDED), "owner.status")
    assert_non_negative_int(owner["owner_penalty_points"], "owner.owner_penalty_points")
    assert isinstance(owner["payout_balance_cents"], int)
    assert_non_negative_int(owner["listed_listing_count"], "owner.listed_listing_count")


def assert_renter(renter: Dict[str, Any]) -> None:
    assert_mutable_common_fields(renter, "renter")
    assert isinstance(renter["display_name"], str) and renter["display_name"]
    assert isinstance(renter["email"], str) and renter["email"]
    assert_iso_date(renter["date_of_birth"], "renter.date_of_birth")
    assert isinstance(renter["license_state_code"], str) and renter["license_state_code"]
    assert isinstance(renter["wallet_credit_cents"], int)
    assert_non_negative_int(renter["renter_penalty_points"], "renter.renter_penalty_points")
    assert_non_negative_int(renter["driving_record_points"], "renter.driving_record_points")
    assert_enum(
        renter["driving_record_status"],
        (
            DrivingRecordStatus.NONE,
            DrivingRecordStatus.CLEAR,
            DrivingRecordStatus.MINOR,
            DrivingRecordStatus.MAJOR,
            DrivingRecordStatus.EXPIRED,
        ),
        "renter.driving_record_status",
    )
    assert_enum(
        renter["towing_verified_tier"],
        (TowingTier.NONE, TowingTier.BASIC, TowingTier.ADVANCED),
        "renter.towing_verified_tier",
    )


def assert_listing(listing: Dict[str, Any]) -> None:
    assert_mutable_common_fields(listing, "listing")
    assert_identifier(listing["owner_id"], "listing.owner_id")
    assert isinstance(listing["nickname"], str) and listing["nickname"]
    assert_enum(listing["vehicle_class"], ALL_VEHICLE_CLASSES, "listing.vehicle_class")
    assert_bool(listing["requires_towing"], "listing.requires_towing")
    assert_non_negative_int(listing["gvwr_lbs"], "listing.gvwr_lbs")
    assert_non_negative_int(listing["length_ft"], "listing.length_ft")
    assert_non_negative_int(
        listing["base_nightly_rate_cents"], "listing.base_nightly_rate_cents"
    )
    assert_non_negative_int(
        listing["included_miles_per_night"], "listing.included_miles_per_night"
    )
    assert_non_negative_int(
        listing["mileage_overage_rate_cents_per_mile"],
        "listing.mileage_overage_rate_cents_per_mile",
    )
    assert isinstance(listing["included_generator_hours_per_night"], (int, float))
    assert_non_negative_int(
        listing["generator_overage_rate_cents_per_hour"],
        "listing.generator_overage_rate_cents_per_hour",
    )
    assert_non_negative_int(listing["min_renter_age"], "listing.min_renter_age")
    assert_bool(listing["delivery_offered"], "listing.delivery_offered")
    assert_non_negative_int(
        listing["delivery_base_fee_cents"], "listing.delivery_base_fee_cents"
    )
    assert_non_negative_int(
        listing["delivery_per_mile_cents"], "listing.delivery_per_mile_cents"
    )
    assert_enum(
        listing["listing_status"],
        (
            ListingStatus.DRAFT,
            ListingStatus.IN_REVIEW,
            ListingStatus.LISTED,
            ListingStatus.SUSPENDED,
            ListingStatus.ARCHIVED,
        ),
        "listing.listing_status",
    )
    assert_enum(
        listing["insurance_status"],
        (InsuranceStatus.PENDING, InsuranceStatus.VERIFIED, InsuranceStatus.EXPIRED),
        "listing.insurance_status",
    )
    assert_non_negative_int(
        listing["inspection_photo_zone_count"], "listing.inspection_photo_zone_count"
    )
    assert_non_negative_int(
        listing["completed_night_count"], "listing.completed_night_count"
    )
    if listing["last_reconciled_at"] is not None:
        assert_utc_timestamp(listing["last_reconciled_at"], "listing.last_reconciled_at")


def assert_vehicle_document(document: Dict[str, Any]) -> None:
    assert_mutable_common_fields(document, "vehicle_document")
    assert_identifier(document["listing_id"], "vehicle_document.listing_id")
    assert_enum(
        document["doc_type"],
        (
            DocType.TITLE,
            DocType.REGISTRATION,
            DocType.INSURANCE_POLICY,
            DocType.INSPECTION_PHOTO,
        ),
        "vehicle_document.doc_type",
    )
    if document["zone"] is not None:
        assert_enum(
            document["zone"],
            (
                Zone.EXTERIOR_FRONT,
                Zone.EXTERIOR_REAR,
                Zone.INTERIOR,
                Zone.ROOF,
                Zone.UNDERCARRIAGE,
            ),
            "vehicle_document.zone",
        )
    if document["expires_on"] is not None:
        assert_iso_date(document["expires_on"], "vehicle_document.expires_on")
    assert isinstance(document["image_ref"], str) and document["image_ref"]
    assert_enum(
        document["verification_status"],
        (
            DocVerificationStatus.PENDING,
            DocVerificationStatus.VERIFIED,
            DocVerificationStatus.SUPERSEDED,
        ),
        "vehicle_document.verification_status",
    )
    assert_bool(document["superseded"], "vehicle_document.superseded")


def assert_renter_qualification(qualification: Dict[str, Any]) -> None:
    assert_append_only_common_fields(qualification, "renter_qualification")
    assert_identifier(qualification["renter_id"], "renter_qualification.renter_id")
    assert_enum(
        qualification["check_type"],
        ("DRIVING_RECORD", "TOWING_EXPERIENCE"),
        "renter_qualification.check_type",
    )
    assert_enum(
        qualification["result"],
        (
            QualificationResult.CLEAR,
            QualificationResult.MINOR,
            QualificationResult.MAJOR,
            QualificationResult.VERIFIED_BASIC,
            QualificationResult.VERIFIED_ADVANCED,
            QualificationResult.UNVERIFIED,
        ),
        "renter_qualification.result",
    )
    assert_non_negative_int(
        qualification["violation_points"], "renter_qualification.violation_points"
    )
    assert_utc_timestamp(qualification["checked_at"], "renter_qualification.checked_at")


def assert_protection_plan(plan: Dict[str, Any]) -> None:
    assert_mutable_common_fields(plan, "protection_plan")
    assert_enum(
        plan["tier"],
        (PlanTier.BASIC, PlanTier.STANDARD, PlanTier.PREMIUM),
        "protection_plan.tier",
    )
    for field in (
        "daily_premium_cents",
        "premium_pct_of_base_bp",
        "deductible_cents",
        "coverage_ceiling_cents",
    ):
        assert_non_negative_int(plan[field], f"protection_plan.{field}")
    assert isinstance(plan["excluded_causes"], list)
    assert isinstance(plan["eligible_vehicle_classes"], list)


def assert_cancellation_policy(policy: Dict[str, Any]) -> None:
    assert_mutable_common_fields(policy, "cancellation_policy")
    assert_enum(
        policy["tier"],
        (PolicyTier.FLEXIBLE, PolicyTier.MODERATE, PolicyTier.STRICT),
        "cancellation_policy.tier",
    )
    for field in (
        "full_refund_hours_before",
        "partial_refund_pct_bp",
        "renter_cancel_penalty_points",
        "owner_cancel_penalty_points",
        "owner_cancel_fee_bp",
    ):
        assert_non_negative_int(policy[field], f"cancellation_policy.{field}")


def assert_pricing_season(season: Dict[str, Any]) -> None:
    assert_mutable_common_fields(season, "pricing_season")
    assert_enum(
        season["season_code"],
        (SeasonCode.PEAK, SeasonCode.SHOULDER, SeasonCode.OFF),
        "pricing_season.season_code",
    )
    for field in ("start_month_day", "end_month_day"):
        value = season[field]
        assert isinstance(value, str) and len(value) == 5 and value[2] == "-", (
            f"pricing_season.{field} must be MM-DD, got {value!r}"
        )
    assert_non_negative_int(season["multiplier_bp"], "pricing_season.multiplier_bp")


def assert_campground(campground: Dict[str, Any]) -> None:
    assert_mutable_common_fields(campground, "campground")
    assert isinstance(campground["name"], str) and campground["name"]
    assert isinstance(campground["state_code"], str) and campground["state_code"]
    assert_non_negative_int(campground["max_rig_length_ft"], "campground.max_rig_length_ft")
    assert_non_negative_int(
        campground["daily_dropoff_capacity"], "campground.daily_dropoff_capacity"
    )
    assert_non_negative_int(
        campground["dropoff_buffer_minutes"], "campground.dropoff_buffer_minutes"
    )
    assert_enum(
        campground["status"],
        (CampgroundStatus.ACCEPTING, CampgroundStatus.CLOSED),
        "campground.status",
    )
    assert_non_negative_int(
        campground["scheduled_assignment_count"], "campground.scheduled_assignment_count"
    )


def assert_booking(booking: Dict[str, Any]) -> None:
    assert_mutable_common_fields(booking, "booking")
    for field in (
        "listing_id",
        "renter_id",
        "protection_plan_id",
        "cancellation_policy_id",
    ):
        assert_identifier(booking[field], f"booking.{field}")
    assert_iso_date(booking["start_date"], "booking.start_date")
    assert_iso_date(booking["end_date"], "booking.end_date")
    assert_enum(
        booking["delivery_option"],
        (DeliveryOption.PICKUP, DeliveryOption.CAMPGROUND_DROPOFF),
        "booking.delivery_option",
    )
    assert_non_negative_int(booking["declared_miles"], "booking.declared_miles")
    assert isinstance(booking["declared_generator_hours"], (int, float))
    assert_non_negative_int(booking["nights"], "booking.nights")
    assert_enum(
        booking["trip_status"],
        (
            TripStatus.REQUESTED,
            TripStatus.OWNER_APPROVED,
            TripStatus.CONFIRMED,
            TripStatus.IN_TRIP,
            TripStatus.RETURNED,
            TripStatus.CLOSED,
            TripStatus.CANCELLED_BY_RENTER,
            TripStatus.CANCELLED_BY_OWNER,
            TripStatus.CANCELLED_BY_PLATFORM,
        ),
        "booking.trip_status",
    )
    assert_enum(
        booking["settlement_status"],
        (
            SettlementStatus.NONE,
            SettlementStatus.HELD,
            SettlementStatus.RECONCILING,
            SettlementStatus.DISPUTED,
            SettlementStatus.SETTLED,
            SettlementStatus.REFUNDED,
        ),
        "booking.settlement_status",
    )
    assert_non_negative_int(
        booking["renter_age_years_at_start"], "booking.renter_age_years_at_start"
    )
    assert_non_negative_int(
        booking["renter_record_points_snapshot"], "booking.renter_record_points_snapshot"
    )
    assert_enum(
        booking["towing_verified_tier"],
        (TowingTier.NONE, TowingTier.BASIC, TowingTier.ADVANCED),
        "booking.towing_verified_tier",
    )
    assert_enum(
        booking["loyalty_tier"],
        (LoyaltyTier.NONE, LoyaltyTier.TIER_1, LoyaltyTier.TIER_2),
        "booking.loyalty_tier",
    )
    for field in (
        "base_subtotal_cents",
        "premium_cents",
        "delivery_fee_cents",
        "loyalty_discount_cents",
        "service_fee_cents",
        "estimated_overage_cents",
        "quoted_total_cents",
        "hold_amount_cents",
        "final_overage_cents",
        "trip_total_overage_cents",
        "late_return_fee_cents",
        "final_total_cents",
        "refund_cents",
        "info_round_count",
    ):
        assert_non_negative_int(booking[field], f"booking.{field}")
    # balance_due_cents may be negative when the hold exceeded the final total.
    assert isinstance(booking["balance_due_cents"], int)


def assert_delivery_assignment(assignment: Dict[str, Any]) -> None:
    assert_mutable_common_fields(assignment, "delivery_assignment")
    assert_identifier(assignment["booking_id"], "delivery_assignment.booking_id")
    assert_identifier(assignment["campground_id"], "delivery_assignment.campground_id")
    assert_utc_timestamp(assignment["window_start"], "delivery_assignment.window_start")
    assert_utc_timestamp(assignment["window_end"], "delivery_assignment.window_end")
    assert_non_negative_int(
        assignment["distance_miles"], "delivery_assignment.distance_miles"
    )
    assert_non_negative_int(
        assignment["setup_fee_cents"], "delivery_assignment.setup_fee_cents"
    )
    assert_non_negative_int(
        assignment["delivery_fee_cents"], "delivery_assignment.delivery_fee_cents"
    )
    assert_enum(
        assignment["status"],
        (
            AssignmentStatus.REQUESTED,
            AssignmentStatus.SCHEDULED,
            AssignmentStatus.WAITLISTED,
            AssignmentStatus.COMPLETED,
            AssignmentStatus.VOIDED,
        ),
        "delivery_assignment.status",
    )
    assert_iso_date(assignment["dropoff_date"], "delivery_assignment.dropoff_date")
    assert_bool(
        assignment["promoted_from_waitlist"], "delivery_assignment.promoted_from_waitlist"
    )


def assert_meter_reading(reading: Dict[str, Any]) -> None:
    assert_append_only_common_fields(reading, "meter_reading")
    assert_identifier(reading["booking_id"], "meter_reading.booking_id")
    assert_enum(
        reading["reading_type"],
        (ReadingType.PRE_TRIP, ReadingType.MID_TRIP, ReadingType.POST_TRIP),
        "meter_reading.reading_type",
    )
    assert_non_negative_int(reading["odometer_miles"], "meter_reading.odometer_miles")
    assert isinstance(reading["generator_hours"], (int, float))
    assert_utc_timestamp(reading["recorded_at"], "meter_reading.recorded_at")


def assert_trip_photo(photo: Dict[str, Any]) -> None:
    assert_append_only_common_fields(photo, "trip_photo")
    assert_identifier(photo["booking_id"], "trip_photo.booking_id")
    assert_enum(
        photo["phase"],
        (PhotoPhase.PRE_TRIP, PhotoPhase.POST_TRIP),
        "trip_photo.phase",
    )
    assert_enum(
        photo["zone"],
        (
            Zone.EXTERIOR_FRONT,
            Zone.EXTERIOR_REAR,
            Zone.INTERIOR,
            Zone.ROOF,
            Zone.UNDERCARRIAGE,
        ),
        "trip_photo.zone",
    )
    assert_bool(photo["damage_flagged"], "trip_photo.damage_flagged")
    assert isinstance(photo["image_ref"], str) and photo["image_ref"]


def assert_damage_claim(claim: Dict[str, Any]) -> None:
    assert_mutable_common_fields(claim, "damage_claim")
    assert_identifier(claim["booking_id"], "damage_claim.booking_id")
    assert_non_negative_int(
        claim["claimed_amount_cents"], "damage_claim.claimed_amount_cents"
    )
    assert isinstance(claim["description"], str) and claim["description"]
    assert_enum(
        claim["status"],
        (
            ClaimStatus.SUBMITTED,
            ClaimStatus.UNDER_REVIEW,
            ClaimStatus.INFO_REQUESTED,
            ClaimStatus.APPROVED,
            ClaimStatus.PARTIAL,
            ClaimStatus.DENIED,
            ClaimStatus.WITHDRAWN,
        ),
        "damage_claim.status",
    )
    if claim["comparison_verdict"] is not None:
        assert_enum(
            claim["comparison_verdict"],
            (
                ComparisonVerdict.PRE_EXISTING,
                ComparisonVerdict.NEW_DAMAGE,
                ComparisonVerdict.NO_VISIBLE_CHANGE,
            ),
            "damage_claim.comparison_verdict",
        )
    for field in (
        "pre_photo_count",
        "post_photo_count",
        "info_rounds_used",
        "gross_amount_cents",
        "renter_charge_cents",
        "plan_paid_cents",
        "owner_payout_cents",
    ):
        assert_non_negative_int(claim[field], f"damage_claim.{field}")


def assert_ledger_entry(entry: Dict[str, Any]) -> None:
    assert_append_only_common_fields(entry, "ledger_entry")
    assert_identifier(entry["booking_id"], "ledger_entry.booking_id")
    assert_enum(
        entry["party"],
        (LedgerParty.RENTER, LedgerParty.OWNER, LedgerParty.PLATFORM),
        "ledger_entry.party",
    )
    assert isinstance(entry["entry_type"], str) and entry["entry_type"]
    assert isinstance(entry["amount_cents"], int)
    if entry["reversal_of_entry_id"] is not None:
        assert_identifier(
            entry["reversal_of_entry_id"], "ledger_entry.reversal_of_entry_id"
        )


def assert_pricing_guidance(guidance: Dict[str, Any]) -> None:
    assert_identifier(guidance["listing_id"], "pricing_guidance.listing_id")
    assert_iso_date(guidance["window_start_date"], "pricing_guidance.window_start_date")
    assert_iso_date(guidance["window_end_date"], "pricing_guidance.window_end_date")
    assert_non_negative_int(guidance["booked_nights"], "pricing_guidance.booked_nights")
    assert isinstance(guidance["utilization_bp"], int)
    assert isinstance(guidance["util_adj_bp"], int)
    assert_enum(
        guidance["season_code"],
        (SeasonCode.PEAK, SeasonCode.SHOULDER, SeasonCode.OFF),
        "pricing_guidance.season_code",
    )
    assert_non_negative_int(
        guidance["season_multiplier_bp"], "pricing_guidance.season_multiplier_bp"
    )
    assert_non_negative_int(
        guidance["suggested_nightly_rate_cents"],
        "pricing_guidance.suggested_nightly_rate_cents",
    )


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_ledger_sums_to_zero(entries: List[Dict[str, Any]]) -> None:
    """A booking's ledger rows sum to exactly zero at all times."""
    total = sum(entry["amount_cents"] for entry in entries)
    assert total == 0, (
        f"booking ledger must sum to exactly zero, got {total} across "
        f"{len(entries)} rows"
    )


def assert_ledger_rows(
    entries: List[Dict[str, Any]], expected: List[tuple]
) -> None:
    """Assert the (party, entry_type, amount_cents) multiset of a ledger."""
    actual = sorted(
        (entry["party"], entry["entry_type"], entry["amount_cents"]) for entry in entries
    )
    assert actual == sorted(expected), (
        f"ledger rows mismatch.\n  expected: {sorted(expected)}\n  actual:   {actual}"
    )


def find_ledger_row(
    entries: List[Dict[str, Any]], party: str, entry_type: str
) -> Dict[str, Any]:
    matches = [
        entry
        for entry in entries
        if entry["party"] == party and entry["entry_type"] == entry_type
    ]
    assert len(matches) == 1, (
        f"expected exactly one {party}/{entry_type} ledger row, found {len(matches)}"
    )
    return matches[0]


def assert_owner_payout_balance_matches_ledger(
    owner_payout_balance_cents: int, entries: List[Dict[str, Any]]
) -> None:
    """payout_balance_cents is the running sum over the owner's OWNER rows."""
    owner_sum = sum(
        entry["amount_cents"]
        for entry in entries
        if entry["party"] == LedgerParty.OWNER
    )
    assert owner_payout_balance_cents == owner_sum, (
        f"owner payout balance {owner_payout_balance_cents} must equal the sum of "
        f"its OWNER ledger rows {owner_sum}"
    )


def assert_scheduled_slot_count(
    campground: Dict[str, Any], scheduled_assignments: List[Dict[str, Any]]
) -> None:
    """scheduled_assignment_count equals the live count of SCHEDULED rows."""
    live = [
        assignment
        for assignment in scheduled_assignments
        if assignment["status"] == AssignmentStatus.SCHEDULED
    ]
    assert campground["scheduled_assignment_count"] == len(live), (
        f"campground scheduled_assignment_count {campground['scheduled_assignment_count']} "
        f"must equal the {len(live)} live SCHEDULED assignments"
    )


def assert_booking_quote_identity(booking: Dict[str, Any]) -> None:
    """The quoted total is the sum of its six published components."""
    expected = (
        booking["base_subtotal_cents"]
        + booking["premium_cents"]
        + booking["delivery_fee_cents"]
        - booking["loyalty_discount_cents"]
        + booking["service_fee_cents"]
        + booking["estimated_overage_cents"]
    )
    assert booking["quoted_total_cents"] == expected, (
        f"quoted_total_cents {booking['quoted_total_cents']} must equal the sum of "
        f"its components {expected}"
    )


def assert_booking_final_total_identity(booking: Dict[str, Any]) -> None:
    """final_total and balance_due follow from the published components."""
    expected_final = (
        booking["base_subtotal_cents"]
        + booking["premium_cents"]
        + booking["delivery_fee_cents"]
        - booking["loyalty_discount_cents"]
        + booking["service_fee_cents"]
        + booking["final_overage_cents"]
        + booking["late_return_fee_cents"]
    )
    assert booking["final_total_cents"] == expected_final, (
        f"final_total_cents {booking['final_total_cents']} must equal {expected_final}"
    )
    expected_balance = booking["final_total_cents"] - booking["hold_amount_cents"]
    assert booking["balance_due_cents"] == expected_balance, (
        f"balance_due_cents {booking['balance_due_cents']} must equal "
        f"final_total minus hold {expected_balance}"
    )


def assert_damage_waterfall(claim: Dict[str, Any], deductible_cents: int) -> None:
    """The renter pays up to the deductible, the plan pays the remainder."""
    gross = claim["gross_amount_cents"]
    expected_renter = min(gross, deductible_cents)
    assert claim["renter_charge_cents"] == expected_renter, (
        f"renter_charge_cents {claim['renter_charge_cents']} must equal "
        f"min(gross, deductible) {expected_renter}"
    )
    assert claim["plan_paid_cents"] == gross - expected_renter, (
        f"plan_paid_cents {claim['plan_paid_cents']} must equal the remainder "
        f"{gross - expected_renter}"
    )
    assert claim["owner_payout_cents"] == gross, (
        f"owner_payout_cents {claim['owner_payout_cents']} must equal the gross {gross}"
    )


def assert_requires_towing_derivation(listing: Dict[str, Any]) -> None:
    """requires_towing is true exactly for the two towed vehicle classes."""
    expected = listing["vehicle_class"] in ("TRAVEL_TRAILER", "FIFTH_WHEEL")
    assert listing["requires_towing"] == expected, (
        f"requires_towing for {listing['vehicle_class']} must be {expected}"
    )


def assert_pagination_meta(
    meta: Dict[str, Any],
    expected_total: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> None:
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"total_count must be {expected_total}, got {meta['total_count']}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"has_more must be {expected_has_more}, got {meta['has_more']}"
        )
