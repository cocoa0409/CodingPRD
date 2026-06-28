"""Entity assertions and domain invariant checkers.

Each assert_{entity}(data) validates the shape and field-level invariants of a
returned resource using the framework's generic validators.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version (full audit quartet)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_service_area(data: dict):
    _assert_common(data)
    assert isinstance(data["zip_code"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["travel_surcharge_cents"], int) and data["travel_surcharge_cents"] >= 0
    assert isinstance(data["euthanasia_allowed"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_clinician(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert data["clinician_role"] in ("VET", "TECH")
    assert data["status"] in ("AVAILABLE", "ON_ROUTE", "OFF_DUTY")


def assert_rolling_clinic(data: dict):
    _assert_common(data)
    assert isinstance(data["plate"], str)
    assert data["controlled_stock_ml"] >= 0
    assert isinstance(data["vaccine_stock_count"], int) and data["vaccine_stock_count"] >= 0
    assert data["status"] in ("IN_DEPOT", "DEPLOYED", "MAINTENANCE")


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["owner_name"], str)
    assert data["species"] in ("DOG", "CAT", "OTHER")
    assert data["weight_kg"] > 0
    assert isinstance(data["home_zip"], str)


def assert_appointment(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_id"], str)
    assert data["visit_type"] in ("EXAM", "VACCINE", "EUTHANASIA")
    assert data["status"] in (
        "REQUESTED", "SCHEDULED", "IN_VISIT", "AWAITING_PAYMENT",
        "COMPLETED", "REFERRED", "CANCELLED",
    )


def assert_route_day(data: dict):
    _assert_common(data)
    assert isinstance(data["clinician_id"], str)
    assert isinstance(data["rolling_clinic_id"], str)
    assert isinstance(data["stop_count"], int) and data["stop_count"] >= 0
    assert data["posture"] in ("OPEN", "LOCKED", "RECONCILED")


def assert_route_stop(data: dict):
    _assert_common(data)
    assert isinstance(data["route_day_id"], str)
    assert isinstance(data["appointment_id"], str)
    assert isinstance(data["sequence"], int)
    assert data["status"] in ("PLANNED", "ARRIVED", "SERVICED", "SKIPPED")


def assert_estimate(data: dict):
    _assert_common(data)
    assert isinstance(data["appointment_id"], str)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["travel_surcharge_cents"], int)
    assert isinstance(data["estimate_total_cents"], int)
    assert data["status"] in ("DRAFT", "APPROVED", "INVOICED", "VOID")


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["estimate_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in ("CARD", "CASH", "CHECK")
    assert data["status"] in ("CAPTURED", "REFUNDED")


def assert_specimen_pickup(data: dict):
    _assert_common(data)
    assert isinstance(data["appointment_id"], str)
    assert data["specimen_type"] in ("BLOOD", "URINE", "TISSUE")
    assert data["status"] in ("COLLECTED", "IN_TRANSIT", "DELIVERED")


def assert_wellness_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["interval_days"], int) and data["interval_days"] >= 1
    assert data["status"] in ("ACTIVE", "PAUSED", "ENDED")


def assert_referral(data: dict):
    _assert_common(data)
    assert isinstance(data["appointment_id"], str)
    assert isinstance(data["hospital_name"], str)
    assert data["status"] in ("OPEN", "ACKNOWLEDGED")


def assert_controlled_med_log(data: dict):
    """Append-only: id + created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["entry_type"] in ("DISPENSE", "WASTE")
    assert data["amount_ml"] > 0


def assert_append_only_no_version(data: dict):
    """A ControlledMedLog entry must not expose updated_at or version."""
    assert "version" not in data, "ControlledMedLog is append-only and must not carry version"
    assert "updated_at" not in data, "ControlledMedLog is append-only and must not carry updated_at"
