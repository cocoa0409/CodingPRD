"""Entity assertions and domain invariant checkers (Junk Removal & Hauling)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Common-field helpers ─────────────────────────────

def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """Append-only line items carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


# ─── Entity assertions ────────────────────────────────

def assert_pricing_policy(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["full_truck_cents"], int) and data["full_truck_cents"] >= 0
    assert isinstance(data["tier_breaks"], list) and len(data["tier_breaks"]) > 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str)
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_crew(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_iso8601_timestamp(data["shift_start_utc"])
    assert is_iso8601_timestamp(data["shift_end_utc"])
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0
    assert isinstance(data["hazmat_certified"], bool)
    assert isinstance(data["reserved_minutes"], int) and data["reserved_minutes"] >= 0
    assert data["status"] in ("ON_DUTY", "OFF_DUTY")


def assert_truck(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ("IN_SERVICE", "OUT_OF_SERVICE")


def assert_haul_job(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["pricing_policy_id"])
    assert data["service_type"] in ("SAME_DAY", "SCHEDULED")
    assert isinstance(data["address"], str)
    assert data["status"] in (
        "DRAFT", "ESTIMATED", "SCHEDULED", "DISPATCHED",
        "ON_SITE", "LOADED", "COMPLETED", "CANCELLED",
    )


def assert_job_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["haul_job_id"])
    assert data["category"] in ("STANDARD", "MATTRESS", "APPLIANCE", "FREON_APPLIANCE")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1


def assert_photo_estimate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["haul_job_id"])
    assert isinstance(data["raw_fraction"], (int, float))
    assert 0 < data["raw_fraction"] <= 1.0
    assert isinstance(data["accepted"], bool)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "SUPERSEDED")


def assert_dispatch(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["haul_job_id"])
    assert is_valid_uuid(data["crew_id"])
    assert is_valid_uuid(data["truck_id"])
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert isinstance(data["window_minutes"], int) and data["window_minutes"] > 0
    assert data["dispatch_status"] in ("RESERVED", "ACTIVE", "RELEASED", "VOIDED")


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["haul_job_id"])
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["total_cents"], int)
    assert data["kind"] in ("SERVICE", "CANCELLATION")
    assert data["billing_status"] in ("DRAFT", "ISSUED", "SETTLED")
    assert data["dispute_status"] in ("NONE", "DISPUTED", "RESOLVED")


def assert_diversion_record(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["haul_job_id"])
    assert data["destination"] in ("DONATION", "RECYCLING")
    assert isinstance(data["tons"], (int, float)) and data["tons"] >= 0


def assert_dump_ticket(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["haul_job_id"])
    assert data["fee_basis"] in ("WEIGHT_BASED", "VOLUME_BASED")
