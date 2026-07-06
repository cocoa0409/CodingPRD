"""Entity assertions and domain invariant checkers for the Mobile Screening API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_mobile_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["modality"] in ["MAMMOGRAPHY", "BLOOD_PANEL", "BONE_DENSITY", "SKIN"]
    assert isinstance(data["daily_capacity"], int) and data["daily_capacity"] >= 1
    assert data["status"] in ["AVAILABLE", "RETIRED"]


def assert_staff(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["role_type"] in ["TECHNOLOGIST", "RADIOLOGIST", "NAVIGATOR", "PHLEBOTOMIST"]
    assert data["modality"] in ["MAMMOGRAPHY", "BLOOD_PANEL", "BONE_DENSITY", "SKIN"]
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_sponsor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["sponsor_type"] in ["EMPLOYER", "GRANT"]


def assert_grant(data: dict):
    _assert_common(data)
    assert isinstance(data["total_budget_cents"], int) and data["total_budget_cents"] >= 0
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["settled_cents"], int)
    assert isinstance(data["remaining_cents"], int)
    assert isinstance(data["is_depleted"], bool)


def assert_grant_conservation(data: dict):
    """§2.8 conservation invariant: remaining_cents == total_budget_cents - committed_cents,
    and settled_cents <= committed_cents (actual burn <= estimated burn)."""
    assert data["remaining_cents"] == data["total_budget_cents"] - data["committed_cents"], (
        f"remaining {data['remaining_cents']} != total {data['total_budget_cents']} - "
        f"committed {data['committed_cents']}"
    )
    assert data["settled_cents"] <= data["committed_cents"], (
        f"settled {data['settled_cents']} must be <= committed {data['committed_cents']}"
    )


def assert_screening_event(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "PUBLISHED", "CLOSED", "CANCELLED"]
    assert isinstance(data["booked_count"], int) and data["booked_count"] >= 0
    assert isinstance(data["window_start_min"], int)
    assert isinstance(data["window_end_min"], int)
    assert data["window_end_min"] > data["window_start_min"]


def assert_participant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["pay_type"] in ["INSURANCE", "SELF_PAY", "GRANT"]
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert data["status"] in ["ACTIVE", "BLOCKED"]


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "SCHEDULED", "CHECKED_IN", "SCREENED", "RESULT_READY", "CLOSED", "CANCELLED", "NO_SHOW"
    ]
    assert isinstance(data["consent_signed"], bool)
    assert isinstance(data["slot_start_min"], int)
    assert isinstance(data["slot_duration_min"], int) and data["slot_duration_min"] >= 1


def assert_referral(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "CONTACTED", "SCHEDULED_FOLLOWUP", "RESOLVED", "LOST_TO_FOLLOWUP"]
    assert data["priority"] in ["ROUTINE", "URGENT"]


def assert_charge(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "ADJUDICATED", "SETTLED", "VOID"]
    assert data["pay_type"] in ["INSURANCE", "SELF_PAY", "GRANT"]
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["grant_covered_cents"], int)
    assert isinstance(data["provisional_patient_responsibility_cents"], int)


def assert_reminder(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "SENT", "CANCELLED"]
    assert data["channel"] in ["SMS", "EMAIL"]
