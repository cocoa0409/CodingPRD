"""Entity assertions and domain invariant checkers.

Each assert_<entity>() validates structural shape against the PRD contract.
Domain-invariant checkers enforce the ledger and occupancy rules described in
PRD 2.9.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_COMMON_REQUIRED = ("id", "created_at", "updated_at", "version")


def _assert_common_fields(data: dict):
    """Every primary resource carries id/created_at/updated_at/version (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 and increments on each mutation"


def assert_market(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["season_start_date"], str)
    assert isinstance(data["season_end_date"], str)
    assert isinstance(data["season_fee_cents"], int)
    assert isinstance(data["daily_fee_cents"], int)
    assert isinstance(data["commission_bps"], int)
    assert isinstance(data["voucher_face_value_cents"], int)
    assert isinstance(data["booth_count"], int) and data["booth_count"] >= 0
    assert isinstance(data["total_commission_accrued_cents"], int)
    assert isinstance(data["total_fees_collected_cents"], int)
    assert isinstance(data["voucher_liability_cents"], int)


def assert_vendor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["market_id"], str)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["contact_email"], str)
    assert data["status"] in ("PROSPECT", "ACTIVE")
    assert isinstance(data["permit_ok"], bool)
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vendor_id"], str)
    assert data["permit_type"] in ("HEALTH", "FIRE", "COTTAGE_FOOD", "RESALE")
    assert isinstance(data["permit_number"], str)
    assert data["status"] in ("PENDING", "VERIFIED", "REJECTED", "EXPIRED")


def assert_application(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vendor_id"], str)
    assert data["product_category"] in (
        "PRODUCE", "DAIRY", "MEAT", "BAKED_GOODS", "PREPARED_FOOD", "CRAFTS", "FLOWERS",
    )
    assert isinstance(data["requires_health_permit"], bool)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED")


def assert_booth(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["market_id"], str)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["grid_row"], int) and data["grid_row"] >= 0
    assert isinstance(data["grid_col"], int) and data["grid_col"] >= 0
    assert data["size_class"] in ("SINGLE", "DOUBLE", "CORNER")
    assert isinstance(data["allowed_categories"], list)
    assert data["status"] in ("OPEN", "SEASON_HELD", "OUT_OF_SERVICE")


def assert_market_day(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["market_id"], str)
    assert isinstance(data["market_date"], str)
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED", "CANCELLED")
    assert isinstance(data["attendance_count"], int) and data["attendance_count"] >= 0


def assert_booth_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["market_id"], str)
    assert isinstance(data["booth_id"], str)
    assert isinstance(data["vendor_id"], str)
    assert data["assignment_type"] in ("SEASON", "DAILY")
    assert data["status"] in (
        "REQUESTED", "WAITLISTED", "RESERVED", "ACTIVE", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["fee_charged_cents"], int) and data["fee_charged_cents"] >= 0
    assert isinstance(data["fee_refunded_cents"], int) and data["fee_refunded_cents"] >= 0


def assert_check_in(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["market_id"], str)
    assert isinstance(data["booth_assignment_id"], str)
    assert isinstance(data["market_day_id"], str)
    assert data["status"] in ("EXPECTED", "PRESENT", "NO_SHOW")


def assert_sales_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["market_id"], str)
    assert isinstance(data["check_in_id"], str)
    assert isinstance(data["gross_sales_cents"], int) and data["gross_sales_cents"] >= 0
    assert isinstance(data["tokens_accepted"], int) and data["tokens_accepted"] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "RECONCILED", "DISPUTED")
    assert isinstance(data["commission_cents"], int) and data["commission_cents"] >= 0


def assert_voucher_batch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["market_id"], str)
    assert isinstance(data["market_day_id"], str)
    assert isinstance(data["tokens_issued"], int) and data["tokens_issued"] > 0
    assert isinstance(data["tokens_redeemed"], int) and data["tokens_redeemed"] >= 0
    assert data["tokens_redeemed"] <= data["tokens_issued"], (
        "tokens_redeemed never exceeds tokens_issued (PRD 3.7)"
    )
    assert data["status"] in ("ISSUED", "CLOSED")


def assert_voucher_redemption(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["market_id"], str)
    assert isinstance(data["voucher_batch_id"], str)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["market_day_id"], str)
    assert isinstance(data["token_count"], int) and data["token_count"] > 0
    assert data["status"] in ("SUBMITTED", "RECONCILED", "REVERSED")
    assert isinstance(data["reimbursed_cents"], int) and data["reimbursed_cents"] >= 0


def assert_market_ledger_nonnegative(data: dict):
    """Market ledger invariants that must hold after any mutation (PRD 2.9)."""
    assert data["total_fees_collected_cents"] >= 0
    assert data["total_commission_accrued_cents"] >= 0
    assert data["voucher_liability_cents"] >= 0
