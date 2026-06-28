"""Entity assertions and domain invariant checkers (PRD §2.4, §3.1-§3.8)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version present (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 (PRD §2.4)"


def assert_merchant(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["ein"], str)
    assert isinstance(data["state_code"], str)
    assert data["status"] in ("ACTIVE", "BLOCKLISTED")
    assert isinstance(data["monthly_revenue_cents"], int)
    assert data["monthly_revenue_cents"] >= 0


def assert_bank_feed(data: dict):
    _assert_common(data)
    assert isinstance(data["merchant_id"], str)
    assert data["status"] in ("FRESH", "STALE")
    assert isinstance(data["avg_daily_balance_cents"], int) and data["avg_daily_balance_cents"] >= 0
    assert isinstance(data["nsf_count_90d"], int) and data["nsf_count_90d"] >= 0
    assert isinstance(data["deposit_volume_cents"], int) and data["deposit_volume_cents"] >= 0


def assert_application(data: dict):
    _assert_common(data)
    assert isinstance(data["merchant_id"], str)
    assert isinstance(data["bank_feed_id"], str)
    assert isinstance(data["requested_limit_cents"], int) and data["requested_limit_cents"] > 0
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "NEEDS_REVISION", "APPROVED", "DECLINED", "EXPIRED",
    )


def assert_credit_line(data: dict):
    _assert_common(data)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["merchant_id"], str)
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] > 0
    assert data["pricing_tier"] in ("TIER_A", "TIER_B", "TIER_C")
    assert isinstance(data["fee_factor_bps"], int)
    assert data["remittance_cadence"] in ("DAILY", "WEEKLY")
    assert data["status"] in (
        "ACTIVE", "FROZEN", "DELINQUENT", "DEFAULTED", "CHARGED_OFF", "CLOSED",
    )
    assert isinstance(data["nsf_strike_count"], int) and data["nsf_strike_count"] >= 0
    assert_credit_line_balance_invariants(data)


def assert_credit_line_balance_invariants(data: dict):
    """Balance invariants that must hold after any operation (PRD §3.3, §3.4)."""
    out_p = data["outstanding_principal_cents"]
    out_f = data["outstanding_fee_cents"]
    avail = data["available_credit_cents"]
    limit = data["credit_limit_cents"]
    assert out_p >= 0, "outstanding principal must be non-negative"
    assert out_f >= 0, "outstanding fee must be non-negative"
    assert avail >= 0, "available credit floored at 0 (PRD §3.3)"
    # available = limit - outstanding_principal, floored at 0 (PRD §3.3).
    assert avail == max(0, limit - out_p), (
        f"available_credit_cents must equal max(0, limit - outstanding_principal): "
        f"avail={avail}, limit={limit}, out_p={out_p}"
    )


def assert_draw(data: dict):
    _assert_common(data)
    assert isinstance(data["credit_line_id"], str)
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] > 0
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert isinstance(data["principal_repaid_cents"], int) and data["principal_repaid_cents"] >= 0
    assert isinstance(data["fee_repaid_cents"], int) and data["fee_repaid_cents"] >= 0
    assert is_iso8601_timestamp(data.get("drawn_at", "")), "drawn_at must be ISO 8601"
    assert data["status"] in ("OUTSTANDING", "REPAID", "WRITTEN_OFF")


def assert_remittance(data: dict):
    _assert_common(data)
    assert isinstance(data["credit_line_id"], str)
    assert is_iso8601_timestamp(data.get("scheduled_for", "")), "scheduled_for must be ISO 8601"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["principal_applied_cents"], int) and data["principal_applied_cents"] >= 0
    assert isinstance(data["fee_applied_cents"], int) and data["fee_applied_cents"] >= 0
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0
    assert data["status"] in ("SCHEDULED", "SETTLED", "FAILED", "CANCELLED")


def assert_line_increase_request(data: dict):
    _assert_common(data)
    assert isinstance(data["credit_line_id"], str)
    assert isinstance(data["latest_bank_feed_id"], str)
    assert isinstance(data["requested_limit_cents"], int) and data["requested_limit_cents"] > 0
    assert data["status"] in ("PENDING", "APPROVED", "DENIED")


def assert_renewal_offer(data: dict):
    _assert_common(data)
    assert isinstance(data["credit_line_id"], str)
    assert isinstance(data["new_fee_factor_bps"], int) and data["new_fee_factor_bps"] > 0
    assert isinstance(data["term_days"], int) and data["term_days"] > 0
    assert isinstance(data["total_fee_cents"], int) and data["total_fee_cents"] >= 0
    assert isinstance(data["equivalent_apr_bps"], int) and data["equivalent_apr_bps"] >= 0
    assert data["status"] in ("OFFERED", "ACCEPTED", "DECLINED", "EXPIRED")


def assert_statement(data: dict):
    _assert_common(data)
    assert isinstance(data["credit_line_id"], str)
    assert is_iso8601_timestamp(data.get("period_start", "")), "period_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("period_end", "")), "period_end must be ISO 8601"
    assert data["status"] in ("OPEN", "FINALIZED")


def assert_ledger_entry(data: dict):
    """LedgerEntry is immutable (PRD §2.4, §2.8): id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "ledger entry id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "LedgerEntry carries no version (PRD §2.4)"
    assert "updated_at" not in data, "LedgerEntry carries no updated_at (PRD §2.4)"
    assert data["entry_type"] in (
        "DRAW_PRINCIPAL", "DRAW_FEE", "PRINCIPAL_REPAYMENT", "FEE_REPAYMENT", "WRITE_OFF",
    )
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["balance_after_cents"], int)


def sum_ledger_amounts(entries: list, entry_type: str) -> int:
    """Total amount_cents over entries of a given entry_type (PRD §2.8)."""
    return sum(e["amount_cents"] for e in entries if e["entry_type"] == entry_type)
