"""Entity assertions and domain invariant checkers (PRD sections 2.4, 3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def assert_rate_card(data: dict):
    _assert_common_fields(data, "RateCard")
    assert isinstance(data["market_code"], str) and data["market_code"]
    assert data["display_type"] in ["STATIC", "DIGITAL"]
    assert isinstance(data["base_weekly_cents"], int)
    assert isinstance(data["illumination_premium_pct"], (int, float))
    assert isinstance(data["traffic_tier_1_threshold"], int)
    assert isinstance(data["traffic_tier_1_uplift_pct"], (int, float))
    assert isinstance(data["traffic_tier_2_threshold"], int)
    assert isinstance(data["traffic_tier_2_uplift_pct"], (int, float))
    assert data["status"] in ["DRAFT", "PUBLISHED", "RETIRED"]


def assert_face(data: dict):
    _assert_common_fields(data, "Face")
    assert isinstance(data["face_code"], str) and data["face_code"]
    assert isinstance(data["structure_code"], str) and data["structure_code"]
    assert isinstance(data["market_code"], str) and data["market_code"]
    assert data["display_type"] in ["STATIC", "DIGITAL"]
    assert isinstance(data["illuminated"], bool)
    assert isinstance(data["daily_traffic_count"], int)
    assert isinstance(data["width_inches"], int)
    assert isinstance(data["height_inches"], int)
    assert data["status"] in [
        "AVAILABLE", "UNDER_MAINTENANCE", "PERMIT_SUSPENDED", "DECOMMISSIONED",
    ]
    assert data["booking_posture"] in ["OPEN", "RESTRICTED", "BLOCKED"]
    assert data.get("current_permit_id") is None or isinstance(data["current_permit_id"], str)


def assert_permit(data: dict):
    _assert_common_fields(data, "Permit")
    assert isinstance(data["face_id"], str) and data["face_id"]
    assert isinstance(data["permit_number"], str) and data["permit_number"]
    assert isinstance(data["jurisdiction"], str) and data["jurisdiction"]
    assert is_iso8601_timestamp(data.get("issued_on", "")), \
        "Permit.issued_on must be ISO 8601"
    assert is_iso8601_timestamp(data.get("expires_on", "")), \
        "Permit.expires_on must be ISO 8601"
    assert data["status"] in [
        "ACTIVE", "RENEWAL_PENDING", "EXPIRED", "SUPERSEDED", "REVOKED",
    ]


def assert_work_order(data: dict):
    _assert_common_fields(data, "MaintenanceWorkOrder")
    assert isinstance(data["face_id"], str) and data["face_id"]
    assert data["order_type"] in [
        "ILLUMINATION_OUTAGE", "STRUCTURAL_REPAIR", "VEGETATION_CLEARANCE",
        "POSTING_DAMAGE",
    ]
    assert data["status"] in [
        "OPEN", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "REOPENED", "CANCELLED",
    ]
    assert isinstance(data["reopen_count"], int)
    if data["status"] == "COMPLETED":
        assert isinstance(data["downtime_hours"], (int, float)), \
            "completed work order must carry downtime_hours"


def assert_advertiser(data: dict):
    _assert_common_fields(data, "AdvertiserAccount")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["exposure_cents"], int)
    assert data["status"] in ["ACTIVE", "CREDIT_HOLD", "SUSPENDED"]


def assert_campaign(data: dict):
    _assert_common_fields(data, "Campaign")
    assert isinstance(data["advertiser_id"], str) and data["advertiser_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["start_date"], str) and data["start_date"]
    assert isinstance(data["end_date"], str) and data["end_date"]
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "ACTIVE", "COMPLETED", "CANCELLED",
    ]
    assert data["billing_status"] in ["UNINVOICED", "INVOICED", "SETTLED"]
    assert isinstance(data["contracted_cents"], int)
    assert isinstance(data["discount_pct"], (int, float))
    assert isinstance(data["net_contracted_cents"], int)
    assert isinstance(data["cancellation_fees_cents"], int)
    assert isinstance(data["production_charges_cents"], int)
    assert data["delivery_posture"] in ["ON_TRACK", "AT_RISK", "UNDER_DELIVERED"]


def assert_flight(data: dict):
    _assert_common_fields(data, "Flight")
    assert isinstance(data["campaign_id"], str) and data["campaign_id"]
    assert isinstance(data["face_id"], str) and data["face_id"]
    assert isinstance(data["rate_card_id"], str) and data["rate_card_id"]
    assert isinstance(data["start_date"], str) and data["start_date"]
    assert isinstance(data["end_date"], str) and data["end_date"]
    assert data["status"] in [
        "HELD", "BOOKED", "ART_CLEARED", "LIVE", "MISSED", "HOLDOVER",
        "COMPLETED", "CANCELLED", "EXPIRED", "RELEASED",
    ]
    assert isinstance(data["weeks"], int) and data["weeks"] >= 1
    assert isinstance(data["pinned_weekly_cents"], int)
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["net_cents"], int)
    assert isinstance(data["discount_pct"], (int, float))
    assert isinstance(data["cancellation_fee_cents"], int)
    assert isinstance(data["missed_days"], int)
    assert isinstance(data["suspension_days_accrued"], int)
    assert isinstance(data["holdover_weeks"], int)
    assert isinstance(data["holdover_charge_cents"], int)
    assert isinstance(data["estimated_impressions"], int)
    assert isinstance(data["delivered_impressions"], int)
    assert isinstance(data["delivery_ratio"], (int, float))


def assert_artwork_order(data: dict):
    _assert_common_fields(data, "ArtworkOrder")
    assert isinstance(data["flight_id"], str) and data["flight_id"]
    assert isinstance(data["creative_code"], str) and data["creative_code"]
    assert data["material"] in ["VINYL", "POLYETHYLENE", "DIGITAL_FILE"]
    assert isinstance(data["width_inches"], int)
    assert isinstance(data["height_inches"], int)
    assert isinstance(data["revision_count"], int)
    assert isinstance(data["production_charge_cents"], int)
    assert data["status"] in [
        "SUBMITTED", "IN_PRODUCTION", "REVISION_REQUESTED", "PRINTED",
        "SHIPPED", "DELIVERED", "CANCELLED",
    ]


def assert_posting_record(data: dict):
    _assert_common_fields(data, "PostingRecord")
    assert isinstance(data["flight_id"], str) and data["flight_id"]
    assert isinstance(data["installer_user_id"], str) and data["installer_user_id"]
    assert isinstance(data["posted_on"], str) and data["posted_on"]
    assert isinstance(data["photo_proof_url"], str) and data["photo_proof_url"]
    assert data["status"] in ["REPORTED", "VERIFIED", "REJECTED"]


def assert_make_good(data: dict):
    _assert_common_fields(data, "MakeGood")
    assert isinstance(data["flight_id"], str) and data["flight_id"]
    assert data["reason"] in [
        "MISSED_POSTING", "ILLUMINATION_OUTAGE", "PERMIT_SUSPENSION",
        "UNDER_DELIVERY",
    ]
    assert isinstance(data["credit_cents"], int)
    assert data["status"] in ["PROPOSED", "APPROVED", "REJECTED", "APPLIED"]
    assert isinstance(data["proposed_by"], str) and data["proposed_by"]


def assert_face_posture_consistency(face: dict):
    """PRD section 2.7: booking_posture is derived from face status."""
    expected = {
        "AVAILABLE": "OPEN",
        "UNDER_MAINTENANCE": "RESTRICTED",
        "PERMIT_SUSPENDED": "BLOCKED",
        "DECOMMISSIONED": "BLOCKED",
    }
    assert face["booking_posture"] == expected[face["status"]], (
        f"face status {face['status']} must imply posture "
        f"{expected[face['status']]}, got {face['booking_posture']}"
    )


def normalize_calendar(calendar):
    """Normalize an availability calendar to a set of (start_date, end_date)
    tuples. The PRD defines calendars as inclusive start_date/end_date
    interval pairs; accept either array-pair or object encoding."""
    normalized = set()
    for interval in calendar:
        if isinstance(interval, dict):
            normalized.add((interval["start_date"], interval["end_date"]))
        else:
            assert len(interval) == 2, f"calendar interval must be a pair: {interval}"
            normalized.add((interval[0], interval[1]))
    return normalized
