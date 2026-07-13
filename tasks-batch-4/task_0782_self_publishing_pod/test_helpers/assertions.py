"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Every resource carries id, created_at, updated_at, and an integer version
    (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_publisher(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["payout_method"] in ("BANK", "PAYPAL")
    assert isinstance(data["reserve_held_cents"], int)
    assert isinstance(data["lifetime_paid_cents"], int)
    assert data["status"] == "ACTIVE"


def assert_title(data: dict):
    _assert_common(data)
    assert isinstance(data["publisher_id"], str) and data["publisher_id"]
    assert isinstance(data["title"], str) and data["title"]
    assert data["status"] in ("DRAFT", "LIVE", "UNLISTED")


def assert_format(data: dict):
    _assert_common(data)
    assert isinstance(data["title_id"], str) and data["title_id"]
    assert data["format_type"] in ("PRINT", "EBOOK", "AUDIO")
    assert data["status"] in ("DRAFT", "CONTENT_LOCKED", "PUBLISHED", "UNLISTED")


def assert_asset(data: dict):
    _assert_common(data)
    assert data["asset_type"] in ("INTERIOR", "COVER")
    assert data["status"] in ("PENDING", "VALIDATED", "REJECTED")


def assert_isbn(data: dict):
    _assert_common(data)
    assert isinstance(data["isbn_13"], str) and data["isbn_13"]
    assert data["status"] in ("FREE", "ASSIGNED", "LOCKED")


def assert_channel(data: dict):
    _assert_common(data)
    assert data["channel_type"] in ("RETAIL", "LIBRARY", "DIRECT")
    assert isinstance(data["supports_formats"], list)


def assert_channel_price(data: dict):
    _assert_common(data)
    assert data["territory"] in ("US", "UK", "EU", "ROW")
    assert isinstance(data["list_price_cents"], int)
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_proof(data: dict):
    _assert_common(data)
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["status"] in ("ORDERED", "APPROVED", "REVISION_REQUESTED")


def assert_distribution_request(data: dict):
    _assert_common(data)
    assert data["territory"] in ("US", "UK", "EU", "ROW")
    assert data["status"] in ("REQUESTED", "APPROVED", "LIVE", "REJECTED", "WITHDRAWN")


def assert_sales_line(data: dict):
    _assert_common(data)
    assert data["line_type"] in ("SALE", "RETURN")
    assert isinstance(data["units"], int) and data["units"] > 0
    assert isinstance(data["gross_royalty_cents"], int)
    assert isinstance(data["reserve_held_cents"], int)
    assert data["status"] in ("PENDING", "STATEMENTED")


def assert_royalty_statement(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACCRUING", "ISSUED", "PAID")
    assert isinstance(data["gross_royalty_cents"], int)
    assert isinstance(data["reserve_held_cents"], int)
