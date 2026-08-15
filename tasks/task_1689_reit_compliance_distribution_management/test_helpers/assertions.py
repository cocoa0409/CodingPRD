"""Entity assertions and domain invariant checkers.

Computed numeric fields on reports, snapshots, sales, declarations and
requirements exist only after the computing transition (PRD §3.3: reports
"carry no computed numbers until locked"), so those fields are asserted
conditionally on the entity having reached the computed state.
"""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_THREE_FRACTION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_common_fields(data: dict):
    """The identity envelope of PRD §2.4 carried by every persisted entity."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_iso8601_millis(value: str):
    """PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits."""
    assert isinstance(value, str) and _THREE_FRACTION_RE.match(value), (
        f"expected ISO 8601 UTC with three fractional digits, got {value!r}"
    )


def _assert_pct(value, name):
    assert isinstance(value, (int, float)), f"{name} must be numeric"
    assert 0 <= value <= 100, f"{name} must be within 0..100, got {value}"


def assert_reit(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["ticker"], str) and data["ticker"]
    assert isinstance(data["charter_ownership_limit_pct"], (int, float))
    assert 0 < data["charter_ownership_limit_pct"] < 50.0
    assert isinstance(data["taxable_year_start"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["current_ep_balance_cents"], int)
    assert isinstance(data["dividend_distribution_deficit_cents"], int)
    assert isinstance(data["five_fifty_blocked"], bool)


def assert_reit_invariants(data: dict):
    """Domain invariants on the REIT ledger fields (PRD §3.5-§3.7)."""
    assert isinstance(data["current_ep_balance_cents"], int), (
        "E&P balance is integer cents"
    )
    assert data["dividend_distribution_deficit_cents"] >= 0, (
        "deficit floors at zero (PRD §3.5: the requirement floors at 0)"
    )


def assert_asset_holding(data: dict):
    assert_common_fields(data)
    assert isinstance(data["reit_id"], str)
    assert isinstance(data["asset_name"], str) and data["asset_name"]
    assert data["asset_class"] in (
        "REAL_ESTATE",
        "QUALIFYING_SECURITY",
        "NON_QUALIFYING",
    )
    assert isinstance(data["held_by_trs"], bool)
    assert isinstance(data["is_dealer_inventory"], bool)
    assert isinstance(data["acquisition_date"], str)
    assert isinstance(data["value_cents"], int)
    assert data["status"] in ("HELD", "SOLD")


def assert_income_item(data: dict):
    assert_common_fields(data)
    assert isinstance(data["reit_id"], str)
    assert isinstance(data["quarter_id"], str)
    assert data["income_class"] in ("RENTS", "MORTGAGE_INTEREST", "NON_QUALIFYING")
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] >= 0
    assert isinstance(data["source_is_trs"], bool)
    assert isinstance(data["accrued_at"], str)


def assert_quarter(data: dict):
    assert_common_fields(data)
    assert isinstance(data["reit_id"], str)
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["status"] in ("OPEN", "LOCKED")


def assert_asset_test_report(data: dict):
    assert_common_fields(data)
    assert isinstance(data["reit_id"], str)
    assert isinstance(data["quarter_id"], str)
    assert data["status"] in ("DRAFT", "LOCKED", "BREACHED")
    if data["status"] in ("LOCKED", "BREACHED"):
        _assert_pct(data["qualifying_75_pct"], "qualifying_75_pct")
        _assert_pct(data["trs_concentration_pct"], "trs_concentration_pct")
        assert isinstance(data["test_75_passed"], bool)
        assert isinstance(data["trs_test_passed"], bool)


def assert_income_test_report(data: dict):
    assert_common_fields(data)
    assert isinstance(data["reit_id"], str)
    assert isinstance(data["quarter_id"], str)
    assert data["status"] in ("DRAFT", "LOCKED", "BREACHED")
    if data["status"] in ("LOCKED", "BREACHED"):
        _assert_pct(data["qualifying_75_pct"], "qualifying_75_pct")
        _assert_pct(data["qualifying_95_pct"], "qualifying_95_pct")
        assert isinstance(data["test_75_passed"], bool)
        assert isinstance(data["test_95_passed"], bool)


def assert_shareholder(data: dict):
    assert_common_fields(data)
    assert isinstance(data["reit_id"], str)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["holder_type"] in ("INDIVIDUAL", "ENTITY")
    assert data["status"] in ("ACTIVE", "FROZEN")


def assert_shareholder_snapshot(data: dict):
    assert_common_fields(data)
    assert isinstance(data["reit_id"], str)
    assert isinstance(data["snapshot_date"], str)
    assert isinstance(data["total_shares_outstanding"], int)
    assert data["total_shares_outstanding"] > 0
    assert data["status"] in ("DRAFT", "FINALIZED")
    if data["status"] == "FINALIZED":
        _assert_pct(data["top5_individual_pct"], "top5_individual_pct")
        assert isinstance(data["five_fifty_passed"], bool)
        assert isinstance(data["violator_shareholder_ids"], list)


def assert_shareholder_position(data: dict):
    assert_common_fields(data)
    assert isinstance(data["snapshot_id"], str)
    assert isinstance(data["shareholder_id"], str)
    assert isinstance(data["shares_held"], int)
    assert data["shares_held"] >= 0


def assert_distribution_requirement(data: dict):
    assert_common_fields(data)
    assert isinstance(data["reit_id"], str)
    assert isinstance(data["taxable_year"], int)
    assert data["status"] in ("DRAFT", "POSTED", "CLOSED")
    assert isinstance(data["taxable_income_cents"], int)
    assert isinstance(data["net_capital_gain_cents"], int)
    if data["status"] in ("POSTED", "CLOSED"):
        assert isinstance(data["required_amount_cents"], int)
        assert data["required_amount_cents"] >= 0
        assert isinstance(data["distributed_amount_cents"], int)
        assert data["distributed_amount_cents"] >= 0
        assert isinstance(data["deficiency_cents"], int)
        assert data["deficiency_cents"] >= 0


def assert_dividend_declaration(data: dict):
    assert_common_fields(data)
    assert isinstance(data["reit_id"], str)
    assert isinstance(data["taxable_year"], int)
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] > 0
    assert isinstance(data["declaration_date"], str)
    assert isinstance(data["record_date"], str)
    assert isinstance(data["payable_date"], str)
    assert data["status"] in (
        "PENDING_APPROVAL",
        "APPROVED",
        "DECLARED",
        "PAID",
        "VOID",
    )
    if data["status"] in ("DECLARED", "PAID"):
        assert isinstance(data["ordinary_cents"], int)
        assert isinstance(data["capital_gain_cents"], int)
        assert isinstance(data["return_of_capital_cents"], int)
        total = (
            data["ordinary_cents"]
            + data["capital_gain_cents"]
            + data["return_of_capital_cents"]
        )
        assert total == data["amount_cents"], (
            "characterization buckets must sum to the gross amount "
            f"({total} != {data['amount_cents']})"
        )
        assert isinstance(data["declared_by_officer_id"], str)
    if data["status"] in ("APPROVED", "DECLARED", "PAID"):
        assert isinstance(data["approved_by_director_id"], str)


def assert_ep_adjustment(data: dict):
    assert_common_fields(data)
    assert isinstance(data["reit_id"], str)
    assert isinstance(data["quarter_id"], str)
    assert data["kind"] in ("TAXABLE_INCOME", "DISALLOWED_DEDUCTION", "FEDERAL_TAX")
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] >= 0
    assert isinstance(data["effective_date"], str)
    assert data["status"] in ("DRAFT", "POSTED")


def assert_asset_sale(data: dict):
    assert_common_fields(data)
    assert isinstance(data["reit_id"], str)
    assert isinstance(data["asset_holding_id"], str)
    assert isinstance(data["sale_price_cents"], int)
    assert data["sale_price_cents"] > 0
    assert isinstance(data["basis_cents"], int)
    assert data["basis_cents"] >= 0
    assert isinstance(data["sale_date"], str)
    assert data["status"] in ("DRAFT", "ANALYZED", "CONFIRMED", "VOID")
    if data["status"] in ("ANALYZED", "CONFIRMED"):
        assert isinstance(data["holding_period_months"], int)
        assert data["holding_period_months"] >= 0
        assert isinstance(data["is_prohibited"], bool)
        assert isinstance(data["prohibited_tax_cents"], int)
        assert data["prohibited_tax_cents"] >= 0


def assert_compliance_disclosure(data: dict):
    assert_common_fields(data)
    assert isinstance(data["reit_id"], str)
    assert data["disclosure_type"] in (
        "ASSET_TEST",
        "INCOME_TEST",
        "FIVE_FIFTY",
        "DISTRIBUTION",
        "PROHIBITED_TRANSACTION",
    )
    assert isinstance(data["reference_id"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["body"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED")
    assert isinstance(data["revision_count"], int)
    assert data["revision_count"] >= 0
