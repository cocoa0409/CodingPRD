"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Generic envelope-side assertions (PRD §2.4) ─────────────────


def assert_common_fields(data: dict):
    """Mutable entities carry id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_append_only_fields(data: dict):
    """Append-only entities (TowAssistEvent) carry id + created_at only (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


# ─── Per-entity assertions ───────────────────────────────────────


def assert_marina(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["harbor_code"], str)
    assert isinstance(data["liveaboard_cap"], int)
    assert data["liveaboard_cap"] >= 0
    assert isinstance(data["liveaboard_current_count"], int)
    assert data["liveaboard_current_count"] >= 0


def assert_slip(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["marina_id"])
    assert isinstance(data["slip_number"], str)
    assert isinstance(data["length_ft"], (int, float))
    assert data["length_ft"] > 0
    assert isinstance(data["beam_ft"], (int, float))
    assert data["beam_ft"] > 0
    assert data["power_amp"] in {"NONE", "A30", "A50", "A100"}
    assert isinstance(data["pumpout_available"], bool)
    assert isinstance(data["liveaboard_allowed"], bool)
    assert isinstance(data["base_daily_rate_cents"], int)
    assert data["base_daily_rate_cents"] >= 0
    assert data["status"] in {"AVAILABLE", "RESERVED", "OCCUPIED", "OUT_OF_SERVICE"}


def assert_vessel(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["tenant_id"])
    assert isinstance(data["name"], str)
    assert isinstance(data["loa_ft"], (int, float))
    assert data["loa_ft"] > 0
    assert isinstance(data["beam_ft"], (int, float))
    assert data["beam_ft"] > 0
    assert isinstance(data["insurance_policy_number"], str)
    assert isinstance(data["insurance_expires_on"], str)
    assert isinstance(data["insurance_coverage_cents"], int)
    assert data["insurance_coverage_cents"] >= 0


def assert_tenant(data: dict):
    assert_common_fields(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["full_name"], str)
    assert data["liveaboard_status"] in {"NONE", "PENDING", "APPROVED", "REVOKED"}


def assert_lease(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["marina_id"])
    assert is_valid_uuid(data["slip_id"])
    assert is_valid_uuid(data["tenant_id"])
    assert is_valid_uuid(data["vessel_id"])
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["is_liveaboard"], bool)
    assert isinstance(data["nightly_rate_cents"], int)
    assert data["nightly_rate_cents"] >= 0
    assert isinstance(data["total_cost_cents"], int)
    assert data["total_cost_cents"] >= 0
    assert data["status"] in {"RESERVED", "ACTIVE", "ENDED", "CANCELLED"}


def assert_pump_out_request(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["lease_id"])
    assert data["status"] in {"PENDING", "COMPLETED", "CANCELLED"}
    assert isinstance(data["charge_cents"], int)
    assert data["charge_cents"] >= 0


def assert_tow_assist_event(data: dict):
    """TowAssistEvent is append-only (PRD §2.4): no updated_at, no version."""
    assert_append_only_fields(data)
    assert is_valid_uuid(data["tenant_id"])
    assert is_valid_uuid(data["vessel_id"])
    assert is_valid_uuid(data["marina_id"])
    assert isinstance(data["incident_distance_nm"], (int, float))
    assert data["incident_distance_nm"] >= 0
    assert data["outcome"] in {"COVERED", "OUT_OF_RADIUS", "INSURANCE_INVALID"}


def assert_transfer_waitlist_entry(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["marina_id"])
    assert is_valid_uuid(data["tenant_id"])
    assert is_valid_uuid(data["from_lease_id"])
    assert is_valid_uuid(data["target_slip_id"])
    assert isinstance(data["position"], int)
    assert data["position"] >= 1
    assert data["status"] in {"QUEUED", "PROMOTED", "CANCELLED", "EXPIRED"}
