"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version (for versioned resources)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def assert_lightweight_fields(data: dict):
    """id + created_at only (MaintenanceStandard, LedgerEntry)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_property(data: dict):
    assert_common_fields(data)
    assert data["registration_status"] in {"ACTIVE", "SUSPENDED", "DEMOLISHED"}
    assert data["foreclosure_status"] in {
        "NONE", "NOTICE_OF_DEFAULT", "LIS_PENDENS", "AUCTION_SCHEDULED", "REO"
    }
    assert isinstance(data["registration_fee_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["lien_balance_cents"], int)
    assert isinstance(data["open_violation_count"], int)


def assert_fine(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"ASSESSED", "DISPUTED", "PAID", "WAIVED", "LIENED"}
    assert isinstance(data["base_amount_cents"], int)
    assert isinstance(data["accrued_amount_cents"], int)


def assert_lien(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"RECORDED", "SATISFIED", "FORECLOSED"}
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["payoff_amount_cents"], int)
    assert isinstance(data["payoff_quoted_cents"], int)


def assert_violation(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"OPEN", "CURED", "ESCALATED", "FINED", "VOIDED"}
