"""Entity assertions and domain invariant checkers (Locksmith & Lockout Dispatch)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_service_job(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert data["job_status"] in (
        "INTAKE", "DISPATCHED", "ON_SITE", "WORK_COMPLETE", "CLOSED", "CANCELLED",
    )
    assert data["payment_status"] in ("UNPAID", "PARTIALLY_PAID", "PAID", "REFUNDED")
    assert data["service_type"] in ("LOCKOUT", "REKEY", "INSTALL", "SAFE")
    assert isinstance(data["amount_due_cents"], int)
    assert isinstance(data["net_paid_cents"], int)
    assert isinstance(data["version"], int)


def assert_technician(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("ON_DUTY", "OFF_DUTY")
    assert isinstance(data["certified_for"], list)
    assert isinstance(data["base_travel_minutes"], int)
    assert isinstance(data["version"], int)


def assert_job_bay(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("OPEN", "CLOSED_FOR_MAINT")
    assert isinstance(data["version"], int)


def assert_dispatch(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("ASSIGNED", "EN_ROUTE", "ARRIVED", "CANCELLED")
    assert isinstance(data["promised_eta_minutes"], int)
    assert isinstance(data["version"], int)


def assert_bay_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("BOOKED", "RELEASED")
    assert isinstance(data["version"], int)


def assert_on_site_quote(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("DRAFTED", "SUBMITTED", "APPROVED", "REJECTED", "VOIDED")
    assert isinstance(data["estimated_total_cents"], int)
    assert isinstance(data["version"], int)


def assert_lock_part(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["part_status"] in ("STOCKED", "DISCONTINUED")
    assert isinstance(data["units_total"], int)
    assert isinstance(data["units_available"], int)
    assert isinstance(data["units_reserved"], int)
    assert isinstance(data["units_committed"], int)
    assert isinstance(data["version"], int)


def assert_lock_part_ledger_invariant(data: dict):
    """Conserved unit ledger (PRD §2.8): total == available + reserved + committed,
    and units_available never negative."""
    assert data["units_available"] >= 0, "units_available must never go negative"
    assert data["units_reserved"] >= 0
    assert data["units_committed"] >= 0
    assert (
        data["units_total"]
        == data["units_available"] + data["units_reserved"] + data["units_committed"]
    ), "units_total must equal available + reserved + committed"


def assert_part_reservation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("RESERVED", "COMMITTED", "RELEASED")
    assert isinstance(data["quantity"], int)
    assert isinstance(data["version"], int)


def assert_payment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("CAPTURED", "REFUNDED")
    assert isinstance(data["captured_amount_cents"], int)
    assert isinstance(data["refunded_amount_cents"], int)
    assert isinstance(data["version"], int)


def assert_warranty_claim(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("FILED", "APPROVED", "DENIED")
    assert isinstance(data["refund_amount_cents"], int)
    assert isinstance(data["version"], int)


def assert_key_authorization_record(data: dict):
    """Append-only compliance record (PRD §2.4): carries only id + created_at,
    no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["auth_kind"] in ("KEY_DUPLICATION", "CODE_RESET", "RESTRICTED_BLANK")
    assert "version" not in data, "KeyAuthorizationRecord has no version field"
    assert "updated_at" not in data, "KeyAuthorizationRecord has no updated_at field"
