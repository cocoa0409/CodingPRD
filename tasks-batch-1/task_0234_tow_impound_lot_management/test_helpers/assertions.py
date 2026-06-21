"""Entity assertions and domain invariant checkers for the Tow & Impound API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_impound_lot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert data["status"] in ("OPEN", "SUSPENDED")
    assert isinstance(data["daily_storage_rate_cents"], int)
    assert isinstance(data["rotation_cursor"], int)
    assert isinstance(data["version"], int)


def assert_tow_provider(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["offers_received_count"], int)
    assert isinstance(data["offers_accepted_count"], int)
    assert isinstance(data["version"], int)


def assert_rotation_assignment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("OFFERED", "ACCEPTED", "DECLINED", "EXPIRED", "CANCELLED")
    assert isinstance(data["version"], int)


def assert_tow_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert data["status"] in (
        "TOWED", "STORED", "RELEASE_AUTHORIZED", "RELEASED",
        "AUCTION_ELIGIBLE", "AUCTIONED", "VOIDED",
    )
    assert data["hold_status"] in ("NONE", "POLICE_HOLD", "EVIDENCE_HOLD")
    assert data["tow_type"] in ("POLICE", "PRIVATE", "ABANDONED")
    assert isinstance(data["version"], int)


def assert_tow_order_money_invariants(data: dict):
    """Monetary invariants that must hold for any TowOrder read (PRD §3.5)."""
    assert isinstance(data["accrued_storage_cents"], int)
    assert isinstance(data["balance_due_cents"], int)
    assert isinstance(data["net_due_cents"], int)
    assert data["accrued_storage_cents"] >= 0
    assert data["balance_due_cents"] >= 0
    assert data["net_due_cents"] >= 0, "net_due_cents floored at 0 (PRD §3.5)"
    assert data["amount_paid_cents"] >= 0


def assert_notification(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in (
        "DRAFT", "SENT", "DELIVERY_CONFIRMED", "CERTIFIED_RETURNED", "UNDELIVERABLE",
    )
    assert data["recipient_type"] in ("OWNER", "LIENHOLDER")
    assert data["method"] in ("CERTIFIED_MAIL", "PUBLICATION", "EMAIL")


def assert_fee_waiver(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("REQUESTED", "UNDER_REVIEW", "APPROVED", "DENIED", "WITHDRAWN")


def assert_auction(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("SCHEDULED", "OPEN", "SETTLED", "CANCELLED")
    assert isinstance(data["gross_proceeds_cents"], int)


def assert_auction_conservation(data: dict):
    """Auction-level proceeds conservation (PRD §3.9)."""
    assert isinstance(data["gross_proceeds_cents"], int)
    assert isinstance(data["distributed_cents"], int)
    assert isinstance(data["lien_payoff_cents"], int)
    assert isinstance(data["surplus_to_owner_cents"], int)
    # Per-order: lot recovery + lien payoff + surplus == gross sale total.
    assert (
        data["distributed_cents"] + data["lien_payoff_cents"] + data["surplus_to_owner_cents"]
        == data["gross_proceeds_cents"]
    ), "waterfall must conserve every cent of gross proceeds (PRD §3.9)"


def assert_storage_ledger_entry(data: dict):
    """StorageLedgerEntry is immutable: id + created_at only (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in ("ACCRUAL", "FREEZE", "RESUME", "SETTLEMENT")
    assert "version" not in data, "StorageLedgerEntry must NOT carry a version field (PRD §2.4)"
    assert "updated_at" not in data, "StorageLedgerEntry must NOT carry an updated_at field (PRD §2.4)"
