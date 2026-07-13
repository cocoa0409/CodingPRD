"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict):
    """id + created_at + updated_at + version present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_lightweight(data: dict):
    """Immutable audit record: id + created_at only (no updated_at / version)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_author(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["payout_balance_cents"], int)


def assert_narrator(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0
    assert isinstance(data["payout_balance_cents"], int)
    assert isinstance(data["active_booked_days"], int)


def assert_title(data: dict):
    _assert_common(data)
    assert isinstance(data["title_name"], str)
    assert data["exclusivity"] in ("EXCLUSIVE", "NON_EXCLUSIVE")
    assert data["territory"] in ("WORLD", "US", "UK", "EU")
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert data["status"] in (
        "DRAFT", "OPEN_FOR_AUDITION", "CASTING", "IN_PRODUCTION",
        "IN_QC", "PUBLISHED", "REVERTED",
    )
    assert data["rights_status"] in ("ACTIVE", "REVERTED")


def assert_audition(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "DECLINED")


def assert_contract(data: dict):
    _assert_common(data)
    assert data["deal_type"] in ("ROYALTY_SHARE", "PER_HOUR")
    assert data["status"] in ("OFFERED", "ACCEPTED", "DECLINED", "SUPERSEDED", "TERMINATED")


def assert_booking(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "CANCELLED", "COMPLETED")


def assert_milestone(data: dict):
    _assert_common(data)
    assert data["milestone_type"] in ("FIFTEEN_MIN", "FULL")
    assert data["status"] in ("SUBMITTED", "APPROVED", "REVISION_REQUESTED", "REJECTED")
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_qc_review(data: dict):
    _assert_lightweight(data)
    assert data["outcome"] in ("PASS", "FAIL")


def assert_channel(data: dict):
    _assert_common(data)
    assert isinstance(data["supported_territories"], list)
    assert 0 <= data["retailer_cut_pct"] < 1


def assert_listing(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "WITHDRAWN")


def assert_sales_event(data: dict):
    _assert_lightweight(data)
    assert isinstance(data["units_sold"], int) and data["units_sold"] >= 0
    assert isinstance(data["units_returned"], int) and 0 <= data["units_returned"] <= data["units_sold"]
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0


def assert_statement(data: dict):
    _assert_common(data)
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert data["status"] in ("PROVISIONAL", "FINALIZED", "PAID", "FROZEN", "REVERSED")
    for field in (
        "gross_sales_cents", "statement_net_cents",
        "narrator_royalty_cents", "author_royalty_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_royalty_partition(data: dict):
    """PRD §3.7: author + narrator cuts always partition the net exactly."""
    assert data["author_royalty_cents"] + data["narrator_royalty_cents"] == data["statement_net_cents"], (
        "author_royalty_cents + narrator_royalty_cents must equal statement_net_cents"
    )
