"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_client(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["alias_name"], str) and data["alias_name"]
    assert data["contact_channel"] in ("EMAIL", "SMS", "PHONE", "NONE")
    assert data["population_type"] in (
        "ENROLLED_STUDENT", "COMMUNITY_RESIDENT", "FACULTY_STAFF",
    )
    assert isinstance(data["enrolled_credits"], int)
    assert data["status"] in ("INTAKE_PENDING", "ACTIVE", "SUSPENDED", "EXITED")
    assert data["risk_tier"] in ("CRISIS", "ELEVATED", "STABLE", None)
    assert isinstance(data["pantry_points_allotment"], int)
    assert isinstance(data["pantry_points_spent_settled"], int)
    assert isinstance(data["pantry_points_spent_reserved"], int)
    assert isinstance(data["lifetime_grant_cents"], int)
    assert isinstance(data["shelter_no_show_count_90d"], int)
    assert isinstance(data["shelter_restricted"], bool)


def assert_staff_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["staff_role"] in (
        "INTAKE_COORDINATOR", "PANTRY_STAFF", "BENEFITS_COUNSELOR",
        "GRANT_REVIEWER", "SHELTER_COORDINATOR",
    )
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["active_case_load"], int)


def assert_intake_assessment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert isinstance(data["monthly_income_cents"], int)
    assert data["housing_status"] in ("STABLE", "COST_BURDENED", "UNSTABLE", "HOMELESS")
    assert isinstance(data["dependents_under_18"], int)
    assert isinstance(data["receives_snap"], bool)
    assert isinstance(data["receives_childcare_subsidy"], bool)
    assert isinstance(data["food_insecurity_score"], int)
    assert isinstance(data["consent_confidential"], bool)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "RETURNED", "VERIFIED",
        "SUPERSEDED", "EXPIRED", "DISCARDED",
    )


def assert_pantry_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["item_name"], str) and data["item_name"]
    assert data["category"] in ("PERISHABLE", "SHELF_STABLE", "HYGIENE", "BABY_CARE")
    assert isinstance(data["point_cost"], int) and data["point_cost"] >= 1
    assert isinstance(data["quantity_on_hand"], int)
    assert isinstance(data["reorder_threshold"], int)
    assert isinstance(data["per_visit_limit"], int)
    assert isinstance(data["restock_flag"], bool)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_pantry_visit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert is_iso8601_timestamp(data.get("visit_date", "")), "visit_date must be ISO 8601"
    assert data["status"] in ("CHECKED_IN", "COMPLETED", "VOIDED")
    assert isinstance(data["provisional_points"], int)
    assert isinstance(data["points_spent"], int)


def assert_visit_line_item(data: dict):
    # Line items carry only id + created_at as common fields (PRD §2.5).
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "line items carry no updated_at"
    assert "version" not in data, "line items carry no version"
    assert is_valid_uuid(data.get("visit_id", "")), "visit_id must be a UUID"
    assert is_valid_uuid(data.get("item_id", "")), "item_id must be a UUID"
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["points_charged"], int)


def assert_benefits_screening(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert data["program"] in ("SNAP", "CHILDCARE", "HOUSING")
    assert data["status"] in (
        "STARTED", "SCREENED", "APPLICATION_ASSISTED",
        "SUBMITTED", "DETERMINED", "WITHDRAWN",
    )
    assert is_valid_uuid(data.get("counselor_id", "")), "counselor_id must be a UUID"


def assert_grant_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert is_valid_uuid(data.get("fund_id", "")), "fund_id must be a UUID"
    assert data["category"] in (
        "RENT", "UTILITY", "FOOD", "MEDICAL", "TRANSPORT", "CHILDCARE",
    )
    assert isinstance(data["requested_cents"], int)
    assert isinstance(data["approved_cents"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "QUEUED", "UNDER_REVIEW", "MORE_INFO_REQUESTED",
        "APPROVED", "DENIED", "DISBURSED", "EXPIRED", "WITHDRAWN",
    )


def assert_grant_fund(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fund_name"], str) and data["fund_name"]
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["allocated_cents"], int) and data["allocated_cents"] > 0
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["disbursed_cents"], int)
    assert isinstance(data["remaining_committed_basis"], int)
    assert isinstance(data["remaining_cash_basis"], int)
    assert data["status"] in ("OPEN", "EXHAUSTED", "CLOSED")


def assert_shelter_bed(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["shelter_site"], str) and data["shelter_site"]
    assert isinstance(data["bed_label"], str) and data["bed_label"]
    assert isinstance(data["features"], list)
    assert data["status"] in ("AVAILABLE", "OUT_OF_SERVICE")


def assert_shelter_stay(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert is_valid_uuid(data.get("bed_id", "")), "bed_id must be a UUID"
    assert isinstance(data["check_in_date"], str)
    assert isinstance(data["planned_nights"], int)
    assert isinstance(data["check_out_exclusive"], str)
    assert isinstance(data["buffer_until_exclusive"], str)
    assert data["status"] in (
        "RESERVED", "OCCUPIED", "CHECKED_OUT", "NO_SHOW", "CANCELLED",
    )


def assert_partner_agency(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agency_name"], str) and data["agency_name"]
    assert isinstance(data["service_categories"], list) and data["service_categories"]
    assert isinstance(data["weekly_capacity"], int) and data["weekly_capacity"] >= 1
    assert isinstance(data["accepts_walk_ins"], bool)
    assert isinstance(data["active_referral_count"], int)
    assert data["status"] in ("ACTIVE", "PAUSED")


def assert_referral(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert is_valid_uuid(data.get("agency_id", "")), "agency_id must be a UUID"
    assert data["service_category"] in (
        "SNAP_APPLICATION", "CHILDCARE_SUBSIDY", "HOUSING_PLACEMENT",
        "LEGAL_AID", "MENTAL_HEALTH",
    )
    assert data["status"] in (
        "INITIATED", "SENT", "ACKNOWLEDGED", "APPOINTMENT_BOOKED",
        "SERVICE_RECEIVED", "DECLINED", "WITHDRAWN", "EXPIRED",
    )


def assert_outreach_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert data["stigma_theme"] in (
        "NORMALIZATION", "PEER_LED", "FACULTY_TRAINING", "RESOURCE_FAIR",
    )
    assert isinstance(data["registered_count"], int)
    assert isinstance(data["attended_count"], int)
    assert data["status"] in ("PLANNED", "OPEN", "FULL", "COMPLETED", "CANCELLED")


def assert_event_registration(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("event_id", "")), "event_id must be a UUID"
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert data["status"] in ("REGISTERED", "CANCELLED", "ATTENDED")


def assert_fund_conservation(fund: dict):
    """Fund cents are conserved: committed + disbursed + remaining_committed
    == allocated (PRD §3.5 remainder readings)."""
    total = (
        fund["committed_cents"]
        + fund["disbursed_cents"]
        + fund["remaining_committed_basis"]
    )
    assert total == fund["allocated_cents"], (
        f"Fund conservation violated: {fund['committed_cents']} + "
        f"{fund['disbursed_cents']} + {fund['remaining_committed_basis']} "
        f"!= {fund['allocated_cents']}"
    )
