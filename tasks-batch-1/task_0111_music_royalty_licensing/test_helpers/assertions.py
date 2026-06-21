"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. LedgerEntry deliberately has no updated_at / version
assertion because it is an append-only audit row (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_rightsholder(data: dict):
    _common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["party_type"] in ("WRITER", "PUBLISHER", "LABEL")
    assert isinstance(data["payee_country"], str)
    assert isinstance(data["minimum_payout_cents"], int) and data["minimum_payout_cents"] >= 0
    assert 0.0 <= data["withholding_pct"] <= 0.30
    assert isinstance(data["lifetime_earned_cents"], int)
    assert isinstance(data["unrecouped_balance_cents"], int)
    assert data["unrecouped_balance_cents"] >= 0, "unrecouped_balance_cents floored at 0"
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_work(data: dict):
    _common(data)
    assert isinstance(data["title"], str)
    assert isinstance(data["iswc"], str)
    assert data["pro_affiliation"] in ("ASCAP", "BMI", "NONE")
    assert isinstance(data["duration_seconds"], int) and data["duration_seconds"] > 0
    assert isinstance(data["shares_locked"], bool)
    assert isinstance(data["split_total_bps"], int)


def assert_composition_share(data: dict):
    _common(data)
    assert isinstance(data["work_id"], str)
    assert isinstance(data["rightsholder_id"], str)
    assert data["role"] in ("WRITER", "PUBLISHER")
    assert 1 <= data["split_bps"] <= 10000


def assert_recording(data: dict):
    _common(data)
    assert isinstance(data["work_id"], str)
    assert isinstance(data["isrc"], str)
    assert isinstance(data["title"], str)
    assert data["release_type"] in ("STREAMING", "PHYSICAL")
    assert isinstance(data["duration_seconds"], int) and data["duration_seconds"] > 0
    assert isinstance(data["shares_locked"], bool)
    assert isinstance(data["split_total_bps"], int)


def assert_recording_share(data: dict):
    _common(data)
    assert isinstance(data["recording_id"], str)
    assert isinstance(data["rightsholder_id"], str)
    assert 1 <= data["split_bps"] <= 10000


def assert_rights_window(data: dict):
    _common(data)
    assert isinstance(data["recording_id"], str)
    assert isinstance(data["territory"], str)
    assert data["rights_type"] in ("SYNC", "MECHANICAL", "PERFORMANCE")
    assert is_iso8601_timestamp(data["term_start"])
    assert is_iso8601_timestamp(data["term_end"])
    assert data["status"] in ("ACTIVE", "REVOKED")


def assert_usage_event(data: dict):
    _common(data)
    assert isinstance(data["recording_id"], str)
    assert data["usage_type"] in ("PERFORMANCE", "MECHANICAL")
    assert isinstance(data["territory"], str)
    assert is_iso8601_timestamp(data["occurred_at"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["gross_revenue_cents"], int)
    assert data["status"] in ("INGESTED", "ALLOCATED", "VOIDED")
    assert isinstance(data["royalty_cents"], int)
    assert isinstance(data["allocated_holder_count"], int)


def assert_sync_license(data: dict):
    _common(data)
    assert isinstance(data["recording_id"], str)
    assert isinstance(data["licensee_id"], str)
    assert data["media_type"] in ("FILM", "TV", "AD", "GAME")
    assert isinstance(data["territory"], str)
    assert isinstance(data["term_months"], int) and data["term_months"] >= 1
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["quoted_fee_cents"], int)
    assert data["status"] in ("DRAFT", "COUNTERED", "ACCEPTED", "EXECUTED", "DECLINED")
    assert isinstance(data["counter_fee_cents"], int)


def assert_advance(data: dict):
    _common(data)
    assert isinstance(data["rightsholder_id"], str)
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] >= 1
    assert 0.0 < data["recoupment_pct"] <= 1.0
    assert isinstance(data["recouped_cents"], int)
    assert 0 <= data["recouped_cents"] <= data["principal_cents"]
    assert data["status"] in ("ACTIVE", "RECOUPED", "WRITTEN_OFF")


def assert_statement(data: dict):
    _common(data)
    assert isinstance(data["rightsholder_id"], str)
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["gross_earnings_cents"], int)
    assert isinstance(data["recoupment_applied_cents"], int)
    assert isinstance(data["withholding_cents"], int)
    assert isinstance(data["net_payable_cents"], int)
    assert data["net_payable_cents"] >= 0, "net_payable_cents floored at 0"
    assert isinstance(data["carried_forward_cents"], int)
    assert data["status"] in ("DRAFT", "FINALIZED", "PAID")


def assert_payout(data: dict):
    _common(data)
    assert isinstance(data["statement_id"], str)
    assert isinstance(data["rightsholder_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("PENDING", "SETTLED", "REVERSED")


def assert_ledger_entry(data: dict):
    """LedgerEntry is append-only: id + created_at only (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["statement_id"], str)
    assert isinstance(data["rightsholder_id"], str)
    assert data["entry_type"] in ("EARNING", "RECOUPMENT", "WITHHOLDING")
    assert data["source_type"] in ("USAGE_EVENT", "SYNC_LICENSE", "ADVANCE", "STATEMENT")
    assert isinstance(data["source_id"], str)
    assert isinstance(data["amount_cents"], int)
