"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape and field types of a serialized
entity. Every entity is a mutable ledger object carrying id, created_at,
updated_at, and version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer >= 1"


def assert_fund(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["vintage_year"], int)
    assert isinstance(data["target_size_cents"], int) and data["target_size_cents"] >= 0
    assert isinstance(data["mgmt_fee_rate_bps"], int)
    assert isinstance(data["carry_rate_bps"], int)
    assert isinstance(data["pref_rate_bps"], int)
    assert isinstance(data["gp_catchup_rate_bps"], int)
    assert isinstance(data["recycling_cap_pct_bps"], int)
    assert isinstance(data["fee_offset_pct_bps"], int)
    assert data["status"] in ("FORMING", "INVESTING", "HARVESTING", "WOUND_DOWN")
    assert isinstance(data["total_committed_cents"], int)
    assert isinstance(data["total_called_cents"], int)
    assert isinstance(data["total_distributed_cents"], int)
    assert isinstance(data["recycled_to_date_cents"], int)


def assert_limited_partner(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["lp_type"] in ("INDIVIDUAL", "INSTITUTION", "FUND_OF_FUNDS", "SOVEREIGN")
    assert isinstance(data["tax_id_last4"], str)
    assert isinstance(data["is_tax_exempt"], bool)
    assert isinstance(data["default_strike_count"], int) and data["default_strike_count"] >= 0


def assert_commitment(data: dict):
    _assert_common(data)
    assert isinstance(data["fund_id"], str)
    assert isinstance(data["lp_id"], str)
    assert isinstance(data["committed_cents"], int) and data["committed_cents"] >= 1
    assert data["status"] in ("PENDING", "ACTIVE", "DEFAULTED", "CLOSED")
    assert isinstance(data["drawn_cents"], int)
    assert isinstance(data["distributed_cents"], int)
    assert isinstance(data["unfunded_cents"], int)
    assert data["unfunded_cents"] >= 0, "unfunded_cents is floored at zero"


def assert_capital_call(data: dict):
    _assert_common(data)
    assert isinstance(data["fund_id"], str)
    assert isinstance(data["call_number"], int) and data["call_number"] >= 1
    assert data["purpose"] in ("INVESTMENT", "MANAGEMENT_FEE", "EXPENSE")
    assert isinstance(data["called_amount_cents"], int) and data["called_amount_cents"] >= 1
    assert data["status"] in (
        "ISSUED", "SETTLED", "PARTIALLY_DEFAULTED", "DEFAULTED", "CANCELLED")
    assert isinstance(data["funded_amount_cents"], int)


def assert_capital_call_allocation(data: dict):
    _assert_common(data)
    assert isinstance(data["capital_call_id"], str)
    assert isinstance(data["commitment_id"], str)
    assert isinstance(data["allocated_amount_cents"], int)
    assert isinstance(data["paid_amount_cents"], int)
    assert data["status"] in ("PENDING", "PAID", "DEFAULTED", "WAIVED")


def assert_portfolio_company(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["sector"], str)
    assert data["status"] in ("PROSPECT", "HELD", "EXITED", "WRITTEN_OFF")


def assert_investment(data: dict):
    _assert_common(data)
    assert isinstance(data["fund_id"], str)
    assert isinstance(data["portfolio_company_id"], str)
    assert isinstance(data["cost_basis_cents"], int) and data["cost_basis_cents"] >= 1
    assert isinstance(data["ownership_pct_bps"], int)
    assert data["status"] in ("ACTIVE", "REALIZED", "IMPAIRED")
    assert isinstance(data["current_mark_cents"], int)
    assert isinstance(data["realized_proceeds_cents"], int)


def assert_valuation_mark(data: dict):
    _assert_common(data)
    assert isinstance(data["investment_id"], str)
    assert isinstance(data["fair_value_cents"], int) and data["fair_value_cents"] >= 0
    assert data["methodology"] in ("LAST_ROUND", "DCF", "COMPARABLES", "WRITE_OFF")
    assert data["status"] in ("DRAFT", "FINAL", "SUPERSEDED")


def assert_management_fee_accrual(data: dict):
    _assert_common(data)
    assert isinstance(data["fund_id"], str)
    assert isinstance(data["gross_fee_cents"], int)
    assert isinstance(data["offset_applied_cents"], int)
    assert isinstance(data["net_fee_cents"], int)
    assert data["net_fee_cents"] >= 0, "net_fee_cents is floored at zero"
    assert data["status"] in ("ACCRUED", "INVOICED", "PAID", "REVERSED")


def assert_distribution_event(data: dict):
    _assert_common(data)
    assert isinstance(data["fund_id"], str)
    assert isinstance(data["source_investment_id"], str)
    assert isinstance(data["gross_amount_cents"], int) and data["gross_amount_cents"] >= 1
    assert data["distribution_type"] in ("RETURN_OF_CAPITAL", "CAPITAL_GAIN", "INCOME")
    assert isinstance(data["recyclable"], bool)
    assert isinstance(data["lp_share_cents"], int)
    assert isinstance(data["gp_carry_cents"], int)
    assert isinstance(data["recycled_amount_cents"], int)
    assert data["status"] in ("DECLARED", "PAID", "RECALLED", "REVERSED")


def assert_distribution_allocation(data: dict):
    _assert_common(data)
    assert isinstance(data["distribution_event_id"], str)
    assert isinstance(data["commitment_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["clawback_flag"], bool)


def assert_side_letter(data: dict):
    _assert_common(data)
    assert isinstance(data["fund_id"], str)
    assert isinstance(data["lp_id"], str)
    assert isinstance(data["mfn_rank"], int) and data["mfn_rank"] >= 1
    assert isinstance(data["fee_discount_bps"], int)
    assert isinstance(data["excused_purposes"], list)
    assert data["status"] in ("PROPOSED", "EXECUTED", "TERMINATED")


def assert_commitment_ledger_consistent(data: dict):
    """Invariant: unfunded_cents == max(0, committed_cents - drawn_cents)."""
    expected_unfunded = max(0, data["committed_cents"] - data["drawn_cents"])
    assert data["unfunded_cents"] == expected_unfunded, (
        f"unfunded_cents {data['unfunded_cents']} != "
        f"max(0, committed {data['committed_cents']} - drawn {data['drawn_cents']})"
    )
