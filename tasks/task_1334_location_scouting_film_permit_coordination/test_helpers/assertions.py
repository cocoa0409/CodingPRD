"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be a positive integer"
    )


def assert_production(data: dict):
    _assert_common_fields(data, "Production")
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["production_company"], str) and data["production_company"]
    assert isinstance(data["cast_size"], int)
    assert isinstance(data["umbrella_liability_limit_cents"], int)
    assert data["status"] in ["PREP", "ACTIVE", "WRAPPED", "CANCELLED"]


def assert_jurisdiction(data: dict):
    _assert_common_fields(data, "Jurisdiction")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    for field in ("lead_time_business_days", "notification_lead_calendar_days",
                  "notification_radius_ft", "base_fee_cents", "per_day_fee_cents",
                  "per_lane_fee_cents", "large_cast_threshold", "large_cast_multiplier_bps",
                  "min_liability_limit_cents", "police_monitor_lane_threshold"):
        assert isinstance(data[field], int), f"Jurisdiction.{field} must be an integer"
    assert isinstance(data["holidays"], list)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_location(data: dict):
    _assert_common_fields(data, "Location")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["address"], str) and data["address"]
    assert is_valid_uuid(data["jurisdiction_id"])
    assert is_valid_uuid(data["owner_id"])
    assert isinstance(data["deposit_floor_cents"], int)
    assert isinstance(data["buffer_days"], int)
    assert isinstance(data["max_shoot_hours_per_day"], int)
    assert data["status"] in ["SCOUTING", "AGREEMENT_EXECUTED", "RETIRED"]


def assert_location_owner(data: dict):
    _assert_common_fields(data, "LocationOwner")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["default_day_rate_cents"], int)


def assert_location_booking(data: dict):
    _assert_common_fields(data, "LocationBooking")
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["location_id"])
    assert isinstance(data["booking_start_date"], str)
    assert isinstance(data["booking_end_date"], str)
    assert data["status"] in ["CONFIRMED", "RELEASED"]


def assert_scout_package(data: dict):
    _assert_common_fields(data, "ScoutPackage")
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["location_id"])
    assert isinstance(data["photo_count"], int)
    assert isinstance(data["coverage_score_pct"], int)
    assert isinstance(data["scout_date"], str)
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED"]


def assert_owner_agreement(data: dict):
    _assert_common_fields(data, "OwnerAgreement")
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["location_id"])
    assert isinstance(data["shoot_start_date"], str)
    assert isinstance(data["shoot_end_date"], str)
    assert isinstance(data["round_count"], int)
    assert isinstance(data["max_rounds"], int)
    assert data["status"] in ["DRAFT", "PROPOSED", "COUNTERED", "EXECUTED", "COLLAPSED"]


def assert_permit_application(data: dict):
    _assert_common_fields(data, "PermitApplication")
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["location_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["shoot_start_date"], str)
    assert isinstance(data["shoot_end_date"], str)
    assert isinstance(data["closed_lanes"], int)
    assert isinstance(data["shoot_hours_per_day"], int)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "CONDITIONALLY_APPROVED",
        "ISSUED", "DENIED", "SUPERSEDED", "EXPIRED", "WITHDRAWN",
    ]


def assert_street_closure(data: dict):
    _assert_common_fields(data, "StreetClosure")
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["permit_application_id"])
    assert isinstance(data["street_segment"], str) and data["street_segment"]
    assert is_iso8601_timestamp(data["closure_start"])
    assert is_iso8601_timestamp(data["closure_end"])
    assert data["status"] in ["REQUESTED", "APPROVED", "ACTIVE", "COMPLETED", "CANCELLED"]


def assert_notification_record(data: dict):
    _assert_common_fields(data, "NotificationRecord")
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["permit_application_id"])
    assert is_iso8601_timestamp(data["posted_at"])
    assert isinstance(data["households_reached"], int)
    assert isinstance(data["radius_ft_used"], int)
    assert isinstance(data["calendar_days_before_shoot"], int)
    assert isinstance(data["notification_adequate"], bool)
    assert data["status"] in ["POSTED", "ACKED", "DEFICIENT"]


def assert_insurance_certificate(data: dict):
    _assert_common_fields(data, "InsuranceCertificate")
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["insurer_name"], str) and data["insurer_name"]
    assert isinstance(data["umbrella_limit_cents"], int)
    assert isinstance(data["indemnity_clause_ref"], str)
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["expiry_date"], str)
    assert data["status"] in ["PRESENTED", "VERIFIED", "REJECTED", "LAPSED"]


def assert_deposit_account(data: dict):
    _assert_common_fields(data, "DepositAccount")
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["location_id"])
    assert isinstance(data["required_amount_cents"], int)
    assert isinstance(data["held_amount_cents"], int)
    assert isinstance(data["claimed_amount_cents"], int)
    assert isinstance(data["released_amount_cents"], int)
    assert data["status"] in ["OPEN", "FUNDED", "SETTLING", "CLOSED"]


def assert_walkthrough_report(data: dict):
    _assert_common_fields(data, "WalkthroughReport")
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["location_id"])
    assert data["kind"] in ["PRE", "POST"]
    assert isinstance(data["damage_item_count"], int)
    assert isinstance(data["damage_claim_cents"], int)
    assert isinstance(data["signed_by_owner"], bool)
    assert isinstance(data["signed_by_manager"], bool)
    assert data["status"] in ["DRAFT", "SIGNED", "DISPUTED", "FINAL"]


def assert_monitor_assignment(data: dict):
    _assert_common_fields(data, "MonitorAssignment")
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["shoot_day_id"])
    assert data["monitor_type"] in ["POLICE", "FIRE", "FILM_OFFICER"]
    assert isinstance(data["officer_badge"], str) and data["officer_badge"]
    assert isinstance(data["hours_booked"], int)
    assert isinstance(data["checked_in"], bool)
    assert data["status"] in ["ASSIGNED", "CONFIRMED", "RELEASED", "NO_SHOW"]


def assert_shoot_day(data: dict):
    _assert_common_fields(data, "ShootDay")
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["permit_application_id"])
    assert is_valid_uuid(data["location_id"])
    assert isinstance(data["shoot_date"], str)
    assert isinstance(data["planned_hours"], int)
    assert isinstance(data["overtime_minutes"], int)
    assert isinstance(data["monitors_required"], int)
    assert isinstance(data["monitors_confirmed"], int)
    assert data["compliance_status"] in ["COMPLIANT", "DEGRADED", "VIOLATION"]
    assert data["status"] in ["PLANNED", "READY", "IN_PROGRESS", "COMPLETED", "CANCELLED", "SHUT_DOWN"]


def assert_complaint(data: dict):
    _assert_common_fields(data, "Complaint")
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["shoot_day_id"])
    assert data["category"] in ["NOISE", "PARKING", "PROPERTY_DAMAGE", "HOURS_VIOLATION", "OTHER"]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert is_iso8601_timestamp(data["filed_at"])
    assert is_iso8601_timestamp(data["response_due_at"])
    assert isinstance(data["resolution_note"], str)
    assert data["status"] in ["OPEN", "ACKNOWLEDGED", "RESOLVED", "ESCALATED"]


def assert_deposit_money_partition(data: dict):
    """Deposit invariant: after settle, held == claimed + released exactly."""
    assert data["held_amount_cents"] == data["claimed_amount_cents"] + data["released_amount_cents"], (
        "Deposit money partition invariant violated: "
        f"held {data['held_amount_cents']} != claimed {data['claimed_amount_cents']} "
        f"+ released {data['released_amount_cents']}"
    )
