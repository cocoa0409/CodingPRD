"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the common system fields (PRD §2.4) plus the
entity-specific fields. Invariant helpers encode the conserved quantities of §2.7.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_fiscal_year(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["total_equity_cents"], int)
    assert isinstance(data["total_patronage_cents"], int)


def assert_member(data: dict):
    _assert_common(data)
    assert data["membership_status"] in ("PENDING", "ACTIVE", "LAPSED", "DROPPED")
    assert isinstance(data["member_number"], int)
    assert isinstance(data["equity_paid_in_cents"], int)
    assert isinstance(data["patronage_cents_ytd"], int)
    assert isinstance(data["is_working_member"], bool)


def assert_vendor(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "APPROVED", "SUSPENDED")


def assert_product(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "RECALLED", "DISCONTINUED")
    assert data["department"] in ("GROCERY", "PRODUCE", "BULK", "CAFE_DELI")
    assert data["unit_type"] in ("EACH", "WEIGHT")
    assert isinstance(data["qty_on_hand_total"], int)
    assert isinstance(data["needs_reorder"], bool)


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "POSTED")
    # Lot units are conserved across the lot's lifetime (PRD §2.7).
    assert (
        data["received_qty"] == data["qty_on_hand"] + data["qty_sold"] + data["qty_shrunk"]
    ), "received_qty must equal on_hand + sold + shrunk"


def assert_sale(data: dict):
    _assert_common(data)
    assert data["checkout_status"] in ("BUILDING", "FINALIZED")
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["total_cents"] == data["subtotal_cents"] + data["tax_total_cents"]


def assert_board_proposal(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "UNDER_REVIEW", "VOTING", "APPROVED", "REJECTED", "WITHDRAWN"
    )


def assert_patronage_allocation(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "FINALIZED", "SUPERSEDED")


def assert_equity_conserved(fiscal_year: dict, member_equities: list):
    """PRD §2.7: OPEN fiscal year total_equity_cents == sum of non-DROPPED member equity."""
    assert fiscal_year["total_equity_cents"] == sum(member_equities), (
        f"total_equity_cents {fiscal_year['total_equity_cents']} != "
        f"sum of member equity {sum(member_equities)}"
    )
