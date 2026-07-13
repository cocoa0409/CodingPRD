"""Entity assertions and domain invariant checkers.

Uses the framework generic validators internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_municipality(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert 0 <= data["revenue_share_pct"] <= 1
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    for f in ("revenue_share_accrued_cents", "lifetime_rebate_cents",
              "lifetime_penalty_cents", "balance_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer number of cents"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_municipality_balance_invariant(data: dict):
    """balance_cents = revenue_share_accrued_cents + lifetime_rebate_cents
    - lifetime_penalty_cents  (PRD §2.6)."""
    expected = (data["revenue_share_accrued_cents"]
                + data["lifetime_rebate_cents"]
                - data["lifetime_penalty_cents"])
    assert data["balance_cents"] == expected, (
        f"balance_cents {data['balance_cents']} != derived {expected}")


def assert_mill(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["commodity_focus"] in (
        "OCC", "MIXED_PAPER", "PET", "HDPE", "ALUMINUM", "STEEL", "GLASS")
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_commodity_index(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")
    assert isinstance(data["price_cents_per_ton"], int)


def assert_sort_line(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("IDLE", "RUNNING", "DOWN")
    assert isinstance(data["total_downtime_minutes"], int)
    assert data["total_processed_tons"] >= 0
    assert data["throughput_tph"] >= 0


def assert_downtime_event(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data["downtime_minutes"], int)
    assert data["downtime_minutes"] >= 0


def assert_inbound_load(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("RECEIVED", "AUDITED", "PENDING_REAUDIT", "CLOSED")
    assert isinstance(data["provisional_adjustment_cents"], int)
    assert isinstance(data["final_adjustment_cents"], int)


def assert_load_mass_balance(data: dict):
    """baled_tons + residual_tons + unbaled_remaining_tons == net_tons (PRD §3.5)."""
    total = data["baled_tons"] + data["residual_tons"] + data["unbaled_remaining_tons"]
    assert abs(total - data["net_tons"]) < 1e-6, (
        f"mass balance broken: {total} != net_tons {data['net_tons']}")


def assert_bale(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("BALED", "STAGED", "SHIPPED", "SETTLED", "VOIDED")
    assert data["quality_grade"] in ("A", "B", "C")
    assert data["commodity"] in (
        "OCC", "MIXED_PAPER", "PET", "HDPE", "ALUMINUM", "STEEL", "GLASS")


def assert_mill_shipment(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("BUILDING", "SHIPPED", "SETTLED", "DISPUTED")
    assert isinstance(data["gross_settlement_cents"], int)


def assert_municipal_statement(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("OPEN", "FINALIZED", "SUPERSEDED")
    for f in ("total_revenue_share_cents", "total_rebate_cents",
              "total_penalty_cents", "net_payable_cents"):
        assert isinstance(data[f], int)


def assert_revenue_posting(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert data["posting_type"] in ("REVENUE_SHARE", "REBATE", "PENALTY", "REVERSAL")
    assert isinstance(data["amount_cents"], int)
    # Append-only: no version / updated_at (PRD §2.4)
    assert "version" not in data, "RevenueSharePosting must not carry a version field"
    assert "updated_at" not in data, "RevenueSharePosting must not carry updated_at"
