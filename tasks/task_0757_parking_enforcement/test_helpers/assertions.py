"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """Mutable entities carry id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_config_fields(data: dict):
    """Immutable configuration records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def assert_officer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["badge_number"], str) and len(data["badge_number"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0


def assert_beat(data: dict):
    assert_config_fields(data)
    assert data["patrol_zone"] in {"DOWNTOWN", "RESIDENTIAL", "SCHOOL"}


def assert_hearing_room(data: dict):
    assert_config_fields(data)


def assert_violation_code(data: dict):
    assert_common_fields(data)
    assert isinstance(data["base_fine_cents"], int) and data["base_fine_cents"] >= 0
    assert isinstance(data["is_booting_eligible"], bool)
    assert data["status"] in {"ACTIVE", "RETIRED"}


def assert_shift(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"OPEN", "CLOSED"}
    assert is_valid_uuid(data["officer_id"])
    assert is_valid_uuid(data["beat_id"])


def assert_vehicle(data: dict):
    assert_common_fields(data)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0
    assert isinstance(data["projected_balance_cents"], int)
    assert data["projected_balance_cents"] >= 0
    assert isinstance(data["unpaid_citation_count"], int)
    assert data["unpaid_citation_count"] >= 0
    assert data["scofflaw_status"] in {"NONE", "SCOFFLAW", "BOOT_ELIGIBLE", "TOW_ELIGIBLE"}
    assert isinstance(data["has_active_registration_hold"], bool)


def assert_citation(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"ISSUED", "CONTESTED", "UPHELD", "DISMISSED", "PAID", "VOID"}
    assert data["issued_via"] in {"LPR", "HANDHELD"}
    assert isinstance(data["fine_amount_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["amount_due_cents"], int)
    assert data["amount_due_cents"] >= 0


def assert_payment(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"PENDING", "SETTLED", "REFUNDED"}
    assert data["method"] in {"CARD", "ECHECK"}
    assert isinstance(data["amount_cents"], int)


def assert_contest(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"SUBMITTED", "HEARING_SCHEDULED", "CLOSED_UPHELD", "CLOSED_DISMISSED"}


def assert_hearing(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"SCHEDULED", "HELD"}
    assert isinstance(data["adjournment_count"], int) and data["adjournment_count"] >= 0


def assert_boot_tow_order(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"ORDERED", "APPLIED", "RELEASED", "CANCELLED"}
    assert data["order_type"] in {"BOOT", "TOW"}
    assert data["origin"] in {"AUTO", "MANUAL"}


def assert_registration_hold(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"PLACED", "CLEARED"}
