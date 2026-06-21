"""Entity assertions and domain invariant checkers (Roadside Assistance Dispatch)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def assert_membership_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ["BASIC", "PLUS", "PREMIER"], f"bad tier {data['tier']!r}"
    assert isinstance(data["annual_service_limit"], int) and data["annual_service_limit"] >= 1
    assert data["per_incident_mileage_cap_miles"] >= 0
    assert isinstance(data["overage_rate_cents_per_mile"], int) and data["overage_rate_cents_per_mile"] >= 0
    assert isinstance(data["priority_weight"], int) and data["priority_weight"] >= 1
    assert isinstance(data["covered_service_types"], list) and len(data["covered_service_types"]) >= 1
    assert isinstance(data["base_service_fee_cents"], int) and data["base_service_fee_cents"] >= 0


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_id"], str) and is_valid_uuid(data["plan_id"])
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ["ACTIVE", "SUSPENDED"], f"bad member status {data['status']!r}"
    assert is_iso8601_timestamp(data.get("annual_period_start", "")), "annual_period_start must be ISO 8601"
    assert isinstance(data["services_used_this_year"], int) and data["services_used_this_year"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_service_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert data["status"] in ["AVAILABLE", "ON_JOB", "OFFLINE"], f"bad provider status {data['status']!r}"
    assert isinstance(data["capabilities"], list) and len(data["capabilities"]) >= 1
    assert 0.0 <= data["rating"] <= 5.0, f"rating out of range: {data['rating']}"
    assert data["active_call_id"] is None or is_valid_uuid(data["active_call_id"])


def assert_provider_shift(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["provider_id"])
    assert is_iso8601_timestamp(data["shift_start"])
    assert is_iso8601_timestamp(data["shift_end"])
    assert data["status"] in ["SCHEDULED", "CANCELLED"], f"bad shift status {data['status']!r}"


def assert_depot(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["bay_count"], int) and data["bay_count"] >= 1
    assert isinstance(data["cleanup_buffer_minutes"], int) and data["cleanup_buffer_minutes"] >= 0
    assert isinstance(data["occupied_bays"], int) and 0 <= data["occupied_bays"] <= data["bay_count"], \
        "occupied_bays must never exceed bay_count"


def assert_bay_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["depot_id"])
    assert is_valid_uuid(data["service_call_id"])
    assert is_iso8601_timestamp(data["reserved_from"])
    assert is_iso8601_timestamp(data["reserved_until"])
    assert data["status"] in ["ACTIVE", "RELEASED"], f"bad reservation status {data['status']!r}"


def assert_service_call(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert data["service_type"] in ["TOW", "JUMP", "LOCKOUT", "FUEL", "TIRE"]
    assert data["status"] in [
        "DISPATCHING", "ASSIGNED", "EN_ROUTE", "COMPLETED", "CANCELLED", "UNFULFILLED"
    ], f"bad call status {data['status']!r}"
    assert data["assigned_provider_id"] is None or is_valid_uuid(data["assigned_provider_id"])
    assert isinstance(data["dispatch_attempts"], int) and data["dispatch_attempts"] >= 0
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["final_cost_cents"], int)
    assert isinstance(data["member_out_of_pocket_cents"], int)


def assert_dispatch_offer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["service_call_id"])
    assert is_valid_uuid(data["provider_id"])
    assert data["status"] in ["OFFERED", "ACCEPTED", "DECLINED", "EXPIRED"], \
        f"bad offer status {data['status']!r}"
    assert isinstance(data["eta_minutes"], int) and data["eta_minutes"] >= 0


def assert_reimbursement_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["service_call_id"])
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] >= 1
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "REJECTED"
    ], f"bad claim status {data['status']!r}"
    assert isinstance(data["approved_amount_cents"], int) and data["approved_amount_cents"] >= 0
