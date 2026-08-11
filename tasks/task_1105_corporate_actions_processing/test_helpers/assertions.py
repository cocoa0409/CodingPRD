"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_security(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert isinstance(data.get("ticker"), str) and data["ticker"]
    assert isinstance(data.get("cusip"), str) and data["cusip"]
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("status") in ("ACTIVE", "SUSPENDED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert isinstance(data.get("account_number"), str)
    assert isinstance(data.get("holder_name"), str)
    assert isinstance(data.get("cash_balance_cents"), int)
    assert isinstance(data.get("total_cost_basis_cents"), int)
    assert isinstance(data.get("pending_entitlement_count"), int)
    assert data.get("status") in ("ACTIVE", "FROZEN", "CLOSED")
    assert isinstance(data.get("version"), int)


def assert_position_lot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("security_id", ""))
    assert data.get("status") in ("OPEN", "FULLY_SURRENDERED")
    assert isinstance(data.get("cost_basis_total_cents"), int)
    assert isinstance(data.get("version"), int)


def assert_event_source(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert data.get("source_type") in ("CUSTODIAN", "VENDOR", "DEPOSITORY")
    assert isinstance(data.get("reliability_weight"), int)
    assert isinstance(data.get("version"), int)


def assert_source_notification(data: dict):
    """Append-only ingest record: id + created_at, NO updated_at/version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert data.get("status") in ("RECEIVED", "MATCHED", "REJECTED")
    assert "updated_at" not in data, "immutable record must not carry updated_at"
    assert "version" not in data, "immutable record must not carry version"


def assert_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data.get("security_id", ""))
    assert data.get("event_type") in (
        "SPLIT", "MERGER", "SPIN_OFF", "CASH_DIVIDEND", "STOCK_DIVIDEND", "RIGHTS_OFFERING",
    )
    assert data.get("status") in (
        "DRAFT", "CONFIRMED", "AMENDED", "BOOKED", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data.get("version"), int)


def assert_event_amendment(data: dict):
    """Append-only audit record: id + created_at, NO updated_at/version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "immutable record must not carry updated_at"
    assert "version" not in data, "immutable record must not carry version"


def assert_entitlement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert data.get("calculation_basis") in ("TRADE_DATE_BASIS", "SETTLED_BASIS")
    assert data.get("status") in (
        "PROJECTED", "FIRM", "SETTLED", "MISSED", "COMPENSATED", "SUPERSEDED",
    )
    assert isinstance(data.get("entitled_shares"), int)
    assert isinstance(data.get("cash_amount_cents"), int)
    assert isinstance(data.get("cash_in_lieu_cents"), int)
    assert isinstance(data.get("version"), int)


def assert_election(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert data.get("status") in (
        "SUBMITTED", "WITHDRAWN", "SUPERSEDED", "APPLIED", "LAPSED", "VOID",
    )
    assert isinstance(data.get("election_seq"), int)
    assert isinstance(data.get("version"), int)


def assert_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data.get("event_id", ""))
    assert data.get("status") in ("POSTED", "REVERSED")
    assert isinstance(data.get("total_whole_shares_credited"), int)
    assert isinstance(data.get("total_cash_credited_cents"), int)
    assert isinstance(data.get("total_cash_in_lieu_cents"), int)
    assert isinstance(data.get("version"), int)


def assert_booking_line(data: dict):
    """Append-only ledger line: id + created_at, NO updated_at/version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data.get("booking_id", ""))
    assert data.get("line_kind") in (
        "LOT_MUTATION", "LOT_CREATION", "CASH_CREDIT", "CASH_DEBIT", "CASH_IN_LIEU",
    )
    assert "updated_at" not in data, "immutable ledger line must not carry updated_at"
    assert "version" not in data, "immutable ledger line must not carry version"


def assert_claim(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("entitlement_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert data.get("review_status") in ("FILED", "APPROVED", "DENIED")
    assert data.get("payment_status") in ("UNPAID", "PAID")
    assert isinstance(data.get("version"), int)


def assert_custodian_statement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data.get("source_id", ""))
    assert data.get("status") in ("RECEIVED", "RECONCILED")
    assert isinstance(data.get("version"), int)


def assert_recon_break(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_valid_uuid(data.get("statement_id", ""))
    assert data.get("break_type") in (
        "POSITION_MISMATCH", "CASH_MISMATCH", "MISSED_ENTITLEMENT",
    )
    assert data.get("status") in ("OPEN", "RESOLVED", "WRITTEN_OFF")
    assert isinstance(data.get("version"), int)


def assert_account_invariants(data: dict):
    """Derived-balance invariants (PRD §2.9)."""
    assert data["total_cost_basis_cents"] >= 0
    assert data["pending_entitlement_count"] >= 0
    assert isinstance(data["cash_balance_cents"], int)
