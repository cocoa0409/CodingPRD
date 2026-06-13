"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_full(data: dict):
    """id + created_at + updated_at + version (mutable entities)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def _assert_common_light(data: dict):
    """id + created_at only (immutable entities: RoyaltyTier, StatementLine)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "immutable entity must not carry version"
    assert "updated_at" not in data, "immutable entity must not carry updated_at"


def assert_author(data: dict):
    _assert_common_full(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["tax_withholding_pct"], (int, float))
    assert 0 <= data["tax_withholding_pct"] <= 1


def assert_agent(data: dict):
    _assert_common_full(data)
    assert isinstance(data["agency_name"], str) and len(data["agency_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0


def assert_contract(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("author_id", "")), "author_id must be a UUID"
    assert data["status"] in ("DRAFT", "ACTIVE", "TERMINATED")
    assert isinstance(data["advance_cents"], int) and data["advance_cents"] >= 0
    assert isinstance(data["unrecouped_advance_cents"], int)
    assert isinstance(data["lifetime_net_units"], int)
    assert 0 <= data["agent_commission_pct"] <= 1
    assert 0 <= data["reserve_pct"] <= 1
    assert data["reserve_hold_periods"] >= 1


def assert_title(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["edition"] >= 1
    assert data["status"] in ("DRAFT", "PUBLISHED", "OUT_OF_PRINT")


def assert_format(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("title_id", "")), "title_id must be a UUID"
    assert data["format_type"] in ("HARDCOVER", "PAPERBACK", "EBOOK", "AUDIO")
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert isinstance(data["active"], bool)


def assert_royalty_tier(data: dict):
    _assert_common_light(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert data["lower_unit"] >= 1
    assert data["upper_unit"] is None or data["upper_unit"] >= data["lower_unit"]
    assert 0 < data["rate"] <= 1


def assert_sales_period(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert isinstance(data["label"], str)
    assert data["sequence"] >= 1
    assert data["status"] in ("OPEN", "CLOSED", "STATEMENTED")


def assert_sales_record(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("period_id", "")), "period_id must be a UUID"
    assert is_valid_uuid(data.get("format_id", "")), "format_id must be a UUID"
    assert data["units_sold"] >= 0
    assert data["units_returned"] >= 0


def assert_returns_reserve(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert data["status"] in ("HELD", "LIQUIDATED")
    assert isinstance(data["reserve_units"], int)
    assert isinstance(data["reserve_held_cents"], int)
    assert isinstance(data["released_cents"], int)
    assert isinstance(data["consumed_cents"], int)


def assert_subsidiary_right(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert data["right_type"] in ("FOREIGN", "AUDIO", "FILM")
    assert isinstance(data["proceeds_cents"], int) and data["proceeds_cents"] > 0
    assert 0 < data["author_share_pct"] <= 1
    assert isinstance(data["author_income_cents"], int)
    assert data["status"] in ("REGISTERED", "STATEMENTED", "VOID")


def assert_author_statement(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert is_valid_uuid(data.get("period_id", "")), "period_id must be a UUID"
    assert data["status"] in ("DRAFT", "FINALIZED", "PAID")
    for f in (
        "gross_royalty_cents",
        "reserve_held_cents",
        "royalty_credited_cents",
        "reserve_released_cents",
        "subsidiary_income_cents",
        "period_earnings_cents",
        "advance_recouped_cents",
        "payable_before_commission_cents",
        "agent_commission_cents",
        "tax_withheld_cents",
        "net_to_author_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be integer cents"


def assert_statement_line(data: dict):
    _assert_common_light(data)
    assert is_valid_uuid(data.get("statement_id", "")), "statement_id must be a UUID"
    assert data["line_type"] in (
        "ROYALTY",
        "RESERVE_WITHHELD",
        "RESERVE_RELEASED",
        "SUBSIDIARY",
        "ADVANCE_RECOUP",
        "AGENT_COMMISSION",
        "TAX_WITHHELD",
        "NET_PAYABLE",
    )
    assert isinstance(data["amount_cents"], int)


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_reserve_conserved(reserve: dict):
    """A liquidated reserve must conserve its dollars exactly:
    reserve_held_cents == released_cents + consumed_cents (PRD §3.8)."""
    assert (
        reserve["released_cents"] + reserve["consumed_cents"]
        == reserve["reserve_held_cents"]
    ), (
        f"reserve not conserved: held={reserve['reserve_held_cents']} "
        f"released={reserve['released_cents']} consumed={reserve['consumed_cents']}"
    )


def assert_statement_waterfall(stmt: dict):
    """The settlement waterfall identities that PRD §3.9 pins."""
    assert (
        stmt["royalty_credited_cents"]
        == stmt["gross_royalty_cents"] - stmt["reserve_held_cents"]
    ), "royalty_credited_cents = gross_royalty_cents - reserve_held_cents"
    assert (
        stmt["period_earnings_cents"]
        == stmt["royalty_credited_cents"]
        + stmt["reserve_released_cents"]
        + stmt["subsidiary_income_cents"]
    ), "period_earnings_cents = royalty_credited + reserve_released + subsidiary_income"
    assert (
        stmt["payable_before_commission_cents"]
        == stmt["period_earnings_cents"] - stmt["advance_recouped_cents"]
    ), "payable_before_commission = period_earnings - advance_recouped"
