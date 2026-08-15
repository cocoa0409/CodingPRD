"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """PRD §2.4 primary-resource system fields."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_principal(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["annual_quota_cents"], int)
    assert isinstance(data["notice_period_days"], int)
    assert data["status"] in ("ACTIVE", "NOTICE_PENDING", "TERMINATED")
    assert isinstance(data["credited_ytd_sales_cents"], int)
    assert isinstance(data["ytd_year"], int)


def assert_agreement(data: dict):
    assert_common_fields(data)
    assert isinstance(data["principal_id"], str)
    assert isinstance(data["territory_codes"], list) and data["territory_codes"]
    assert isinstance(data["specify_share_bp"], int)
    assert isinstance(data["registered_protection_share_bp"], int)
    assert isinstance(data["tail_period_days"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED", "EXPIRED")


def assert_rate_schedule(data: dict):
    assert_common_fields(data)
    assert isinstance(data["principal_id"], str)
    assert isinstance(data["family_rates"], list) and data["family_rates"]
    assert isinstance(data["attainment_tiers"], list) and data["attainment_tiers"]
    assert isinstance(data["registration_bonus_bp"], int)
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_rep(data: dict):
    assert_common_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["territory_codes"], list)
    assert data["status"] in ("ACTIVE", "COMMISSION_HOLD")
    assert isinstance(data["commission_balance_cents"], int)
    assert isinstance(data["outstanding_draw_cents"], int)


def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["spec_territory_code"], str) and data["spec_territory_code"]
    assert isinstance(data["ship_to_territory_code"], str) and data["ship_to_territory_code"]


def assert_registration(data: dict):
    assert_common_fields(data)
    assert isinstance(data["principal_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["rep_id"], str)
    assert isinstance(data["family_code"], str) and data["family_code"]
    assert isinstance(data["project_name"], str)
    assert isinstance(data["renewals_used"], int)
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "EXPIRED", "WITHDRAWN")


def assert_order(data: dict):
    assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["principal_id"], str)
    assert isinstance(data["external_order_ref"], str) and data["external_order_ref"]
    assert is_iso8601_timestamp(data["placed_at"])
    assert isinstance(data["lines"], list) and data["lines"]
    assert data["fulfillment_status"] in ("PLACED", "SHIPPED", "INVOICED", "PAID", "CANCELLED")
    assert data["commission_status"] in ("ATTRIBUTED", "ACCRUED", "SETTLED", "CLOSED")


def assert_order_split(data: dict):
    assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["line_id"], str) and data["line_id"]
    assert data["role"] in ("REGISTERED", "SPECIFY", "SHIP_TO", "HOUSE", "OVERRIDE")
    assert isinstance(data["share_bp"], int)
    assert isinstance(data["is_override"], bool)
    if data["role"] == "HOUSE":
        assert data.get("rep_id") is None, "HOUSE rows carry a null rep_id (PRD §3.4)"
    else:
        assert isinstance(data.get("rep_id"), str)


def assert_rma(data: dict):
    assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["principal_id"], str)
    assert isinstance(data["lines"], list) and data["lines"]
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "CLOSED", "EXPIRED")


def assert_commission_entry(data: dict):
    """Append-only ledger row (PRD §2.4): only id + created_at as system fields."""
    assert is_valid_uuid(data.get("id", "")), f"entry id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"entry created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "version" not in data, "ledger entries must not carry version (append-only)"
    assert "updated_at" not in data, "ledger entries must not carry updated_at (append-only)"
    assert isinstance(data["rep_id"], str)
    assert isinstance(data["principal_id"], str)
    assert data["type"] in (
        "ACCRUAL", "CHARGEBACK", "ADJUSTMENT",
        "STATEMENT_PAYMENT", "DRAW_RECOVERY", "SAMPLE_CHARGE",
    )
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data["business_date"])


def assert_statement(data: dict):
    assert_common_fields(data)
    assert isinstance(data["principal_id"], str)
    assert isinstance(data["period_label"], str) and data["period_label"]
    assert isinstance(data["lines"], list) and data["lines"]
    assert isinstance(data["stated_total_cents"], int)
    assert data["status"] in ("RECEIVED", "IN_RECONCILIATION", "DISPUTED", "SETTLED")


def assert_sample_unit(data: dict):
    assert_common_fields(data)
    assert isinstance(data["principal_id"], str)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["family_code"], str) and data["family_code"]
    assert isinstance(data["value_cents"], int)
    assert data["status"] in ("IN_STOCK", "CHECKED_OUT", "CONVERTED", "WRITTEN_OFF")


def assert_sample_checkout(data: dict):
    assert_common_fields(data)
    assert isinstance(data["sample_unit_id"], str)
    assert isinstance(data["rep_id"], str)
    assert is_iso8601_timestamp(data["checked_out_at"])
    assert is_iso8601_timestamp(data["due_at"])
    assert data["status"] in ("OPEN", "RETURNED", "CONVERTED", "CHARGED")


# ---------------------------------------------------------------------------
# Nested-row helpers used by assertions across the suite
# ---------------------------------------------------------------------------

def order_line(order: dict, line_id: str) -> dict:
    """Return the order line row with the given client-chosen line_id."""
    matches = [ln for ln in order.get("lines", []) if ln.get("line_id") == line_id]
    assert matches, f"order {order.get('id')} has no line {line_id!r}"
    return matches[0]


def statement_line(statement: dict, line_id: str) -> dict:
    """Return the statement line row with the given client-chosen line_id."""
    matches = [ln for ln in statement.get("lines", []) if ln.get("line_id") == line_id]
    assert matches, f"statement {statement.get('id')} has no line {line_id!r}"
    return matches[0]


def splits_for_line(splits: list, line_id: str) -> list:
    """Filter a split-row listing down to one order line."""
    return [row for row in splits if row.get("line_id") == line_id]


def sum_entry_amounts(entries: list, entry_type: str = None) -> int:
    """Algebraic sum of entry amounts, optionally restricted to one type."""
    return sum(
        e["amount_cents"] for e in entries
        if entry_type is None or e.get("type") == entry_type
    )
