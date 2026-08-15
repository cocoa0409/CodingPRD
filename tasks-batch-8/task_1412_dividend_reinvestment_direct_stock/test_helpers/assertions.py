"""Entity assertions and domain invariant helpers."""
from decimal import Decimal

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AcquisitionType,
    BasisMethod,
    DividendEventStatus,
    Election,
    EnrollmentStatus,
    FeeType,
    LedgerEntryType,
    NoticeStatus,
    NoticeType,
    PlanStatus,
    PricingBasis,
    PurchaseOrderStatus,
    PurchaseWindowStatus,
    TransferStatus,
    TransferType,
)


def assert_shares_equal(actual, expected: str, context: str = ""):
    """Compare a share quantity by exact decimal value at 4dp semantics.

    The PRD fixes share quantities as decimal numbers with exactly four
    decimal places; comparing through Decimal makes the check independent of
    JSON numeric/string serialization while still catching rounding drift.
    """
    actual_dec = Decimal(str(actual))
    expected_dec = Decimal(expected)
    assert actual_dec == expected_dec, (
        f"Expected {expected} shares, got {actual!r} {context}".rstrip()
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["issuer_name"], str) and data["issuer_name"]
    assert isinstance(data["ticker"], str) and data["ticker"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in [s.value for s in PlanStatus]
    assert data["pricing_basis"] in [s.value for s in PricingBasis]
    assert data["basis_method"] in [s.value for s in BasisMethod]
    for field in ("ocp_min_cents", "ocp_max_cents", "ocp_fee_min_cents",
                  "sale_fee_cents", "transfer_fee_cents", "enrollment_fee_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_participant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["fee_waiver_eligible"], bool)


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["participant_id"])
    assert is_valid_uuid(data["plan_id"])
    assert data["status"] in [s.value for s in EnrollmentStatus]
    assert data["election"] in [s.value for s in Election]
    assert isinstance(data["total_cost_basis_cents"], int)


def assert_dividend_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["plan_id"])
    assert isinstance(data["amount_per_share_cents"], int)
    assert data["status"] in [s.value for s in DividendEventStatus]


def assert_purchase_window(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["plan_id"])
    assert isinstance(data["price_cents"], int)
    assert data["status"] in [s.value for s in PurchaseWindowStatus]
    assert isinstance(data["submitted_total_cents"], int)


def assert_purchase_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["window_id"])
    assert is_valid_uuid(data["enrollment_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in [s.value for s in PurchaseOrderStatus]


def assert_ledger_entry(data: dict):
    """Ledger entries are immutable: id + created_at only, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 UTC timestamp"
    assert "updated_at" not in data, "ledger entries carry no updated_at"
    assert "version" not in data, "ledger entries carry no version"
    assert is_valid_uuid(data["enrollment_id"])
    assert data["entry_type"] in [s.value for s in LedgerEntryType]


def assert_tax_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert isinstance(data["cost_per_share_cents"], int)
    assert isinstance(data["total_basis_cents"], int)
    assert data["acquisition_type"] in [s.value for s in AcquisitionType]


def assert_fee_assessment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert data["fee_type"] in [s.value for s in FeeType]
    assert isinstance(data["computed_cents"], int)
    assert isinstance(data["charged_cents"], int)
    assert isinstance(data["waived"], bool)


def assert_plan_notice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["plan_id"])
    assert data["notice_type"] in [s.value for s in NoticeType]
    assert data["status"] in [s.value for s in NoticeStatus]
    assert isinstance(data["message"], str)


def assert_transfer_instruction(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["source_enrollment_id"])
    assert data["transfer_type"] in [s.value for s in TransferType]
    assert data["status"] in [s.value for s in TransferStatus]
