"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["sales_tax_rate_bps"], int)
    assert isinstance(data["facility_fee_bps"], int)
    assert isinstance(data["recovery_balance_cents"], int)


def assert_tenant(data: dict):
    _assert_common(data)
    assert data["access_status"] in ("ACTIVE", "REVOKED")
    assert isinstance(data["surplus_balance_cents"], int)


def assert_unit(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "RENTED", "LIEN_NOTICED", "LIEN_MATURED", "IN_AUCTION", "SOLD", "CLEARED",
    )
    assert isinstance(data["past_due_balance_cents"], int)
    assert isinstance(data["lien_amount_provisional_cents"], int)
    assert isinstance(data["lien_amount_final_cents"], int)


def assert_lien_notice(data: dict):
    _assert_common(data)
    assert data["status"] in ("SENT", "CURED", "MATURED", "WITHDRAWN")
    assert is_iso8601_timestamp(data.get("notice_sent_at", "")), "notice_sent_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("cure_deadline", "")), "cure_deadline must be ISO 8601"
    assert isinstance(data["lien_amount_cents"], int)


def assert_auction(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "LIVE", "CLOSED", "CANCELLED", "SETTLED")
    assert data["mode"] in ("ONLINE", "ONSITE")
    assert isinstance(data["high_bid_cents"], int)
    assert isinstance(data["min_next_bid_cents"], int)


def assert_buyer(data: dict):
    _assert_common(data)
    assert data["status"] in ("REGISTERED", "SUSPENDED")
    assert isinstance(data["deposit_available_cents"], int)
    assert isinstance(data["deposit_held_cents"], int)
    assert isinstance(data["deposit_forfeited_cents"], int)


def assert_bid(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "OUTBID", "WINNING", "LOST", "RETRACTED")
    assert isinstance(data["amount_cents"], int)


def assert_sale(data: dict):
    _assert_common(data)
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED", "FORFEITED")
    assert data["cleanout_status"] in ("PENDING", "COMPLETED", "OVERDUE", "VOIDED")
    assert isinstance(data["winning_amount_cents"], int)
    assert isinstance(data["total_due_cents"], int)


def assert_settlement(data: dict):
    _assert_common(data)
    assert data["status"] in ("FINALIZED", "REVERSED")
    assert isinstance(data["gross_proceeds_cents"], int)


def assert_dispute(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "NEEDS_INFO", "UPHELD", "DENIED")


def assert_proceeds_identity(settlement: dict):
    """The waterfall proceeds identity must hold on any settlement record (PRD §3.6, §3.8)."""
    assert (
        settlement["gross_proceeds_cents"]
        == settlement["lien_recovered_cents"]
        + settlement["facility_fee_cents"]
        + settlement["surplus_cents"]
    ), (
        "gross_proceeds_cents must equal lien_recovered_cents + facility_fee_cents + surplus_cents, "
        f"got {settlement}"
    )
