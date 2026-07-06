"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


# ---------------------------------------------------------------------------
# Common validators
# ---------------------------------------------------------------------------

def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"bad created_at: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"bad updated_at: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"bad created_at: {data.get('created_at')!r}"


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------

def assert_funder(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["fiscal_year_start_month"], int)
    assert 1 <= data["fiscal_year_start_month"] <= 12
    assert isinstance(data["grant_cents_total"], int) and data["grant_cents_total"] >= 0
    assert isinstance(data["grant_cents_remaining"], int)
    assert data["reporting_currency"] in ("USD", "CAD", "EUR")


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert -90.0 <= data["location_lat"] <= 90.0
    assert -180.0 <= data["location_lng"] <= 180.0
    assert isinstance(data["accessibility_features"], list)
    assert isinstance(data["languages_supported"], list) and len(data["languages_supported"]) >= 1


def assert_program(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["provider_id"])
    assert is_valid_uuid(data["funder_id"])
    assert data["category"] in (
        "FOOD", "HOUSING", "HEALTHCARE", "MENTAL_HEALTH",
        "EMPLOYMENT", "TRANSPORT", "LEGAL_AID", "CHILDCARE",
    )
    assert isinstance(data["eligibility_income_max_cents"], int) and data["eligibility_income_max_cents"] >= 0
    assert isinstance(data["eligibility_age_min"], int) and 0 <= data["eligibility_age_min"] <= 120
    assert isinstance(data["eligibility_age_max"], int) and 0 <= data["eligibility_age_max"] <= 120
    assert data["eligibility_age_max"] >= data["eligibility_age_min"]
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["capacity_slots_total"], int) and data["capacity_slots_total"] >= 1
    assert isinstance(data["capacity_slots_taken"], int) and data["capacity_slots_taken"] >= 0
    assert data["intake_posture"] in ("OPEN", "RESTRICTED", "CLOSED")
    assert data["funder_reporting_posture"] in ("OPEN", "LOCKED", "ARCHIVED")


def assert_availability_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["program_id"])
    assert is_iso8601_timestamp(data["start_ts"])
    assert is_iso8601_timestamp(data["end_ts"])
    assert isinstance(data["max_slots"], int) and data["max_slots"] >= 1


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["monthly_income_cents"], int) and data["monthly_income_cents"] >= 0
    assert -90.0 <= data["home_lat"] <= 90.0
    assert -180.0 <= data["home_lng"] <= 180.0
    assert data["preferred_language"] in ("EN", "ES", "FR", "ZH", "VI", "AR")
    assert isinstance(data["accessibility_needs"], list)


def assert_intake(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["presenting_needs"], list) and len(data["presenting_needs"]) >= 1
    assert data["urgency"] in ("ROUTINE", "PRIORITY", "EMERGENCY")
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert isinstance(data["disability_flag"], bool)
    assert data["status"] in ("DRAFT", "SCREENED", "CLOSED")


def assert_consent_grant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["provider_id"])
    assert data["scope"] in ("BASIC_CONTACT", "FULL_CASE_FILE", "HEALTHCARE_HIPAA")
    assert is_iso8601_timestamp(data["granted_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ("GRANTED", "REVOKED", "EXPIRED")


def assert_referral(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["intake_id"])
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["consent_grant_id"])
    assert data["transport_mode"] in ("PUBLIC_TRANSIT", "CAR", "WALKING", "AGENCY_SHUTTLE")
    assert isinstance(data["travel_burden_naive_min"], (int, float))
    assert isinstance(data["travel_burden_routed_min"], (int, float))
    assert isinstance(data["eligibility_score"], (int, float))
    assert isinstance(data["provisional_cost_cents"], int)
    assert data["status"] in (
        "PROPOSED", "ACCEPTED", "DECLINED", "SERVICE_IN_PROGRESS",
        "COMPLETED_SUCCESS", "COMPLETED_UNSUCCESSFUL", "WITHDRAWN",
    )


def assert_transport_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["referral_id"])
    assert is_iso8601_timestamp(data["pickup_start_ts"])
    assert is_iso8601_timestamp(data["pickup_end_ts"])
    assert data["mode"] in ("AGENCY_SHUTTLE", "RIDESHARE_VOUCHER")
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] >= 0
    assert data["status"] in ("SCHEDULED", "CANCELLED")


def assert_outcome_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["referral_id"])
    assert data["outcome"] in ("FULLY_MET", "PARTIALLY_MET", "UNMET")
    assert isinstance(data["service_hours"], (int, float)) and data["service_hours"] >= 0
    assert isinstance(data["follow_up_needed"], bool)
    assert isinstance(data["service_cost_final_cents"], int)
    assert data["status"] in ("ACTIVE", "REVERSED")


def assert_funder_report(data: dict):
    """FunderReport has common_fields: false -> ONLY id + created_at.
    updated_at and version MUST NOT appear in the response body per PRD §2.4."""
    _assert_append_only(data)
    assert is_valid_uuid(data["funder_id"])
    assert is_iso8601_timestamp(data["reporting_period_start"])
    assert is_iso8601_timestamp(data["reporting_period_end"])
    assert data["rounding_variant"] in ("PER_REFERRAL_ROUND_THEN_SUM", "SUM_THEN_ROUND")
    assert isinstance(data["total_referrals"], int) and data["total_referrals"] >= 0
    assert isinstance(data["total_completions"], int) and data["total_completions"] >= 0
    assert isinstance(data["total_disbursement_cents"], int) and data["total_disbursement_cents"] >= 0


def assert_funder_report_has_no_version_fields(data: dict):
    """PRD §2.4: FunderReport carries only id and created_at; updated_at and version are absent."""
    assert "version" not in data, f"FunderReport must NOT expose version, saw {data.get('version')!r}"
    assert "updated_at" not in data, f"FunderReport must NOT expose updated_at, saw {data.get('updated_at')!r}"
