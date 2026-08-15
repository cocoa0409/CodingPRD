"""Entity assertions and domain invariant checkers.

Each assert_* validates the common properties the PRD guarantees for every
resource (server-minted UUID id, ISO 8601 created_at/updated_at, integer
version) plus the entity's status enum membership and key field types.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AllowanceStatus,
    AuditStatus,
    DeferredItemKind,
    DifferenceStatus,
    DifferenceType,
    ExtensionStatus,
    FilingStatus,
    JurisdictionLevel,
    NoticeStatus,
    NoticeType,
    PaymentMethod,
    PaymentStatus,
    PositionStatus,
    TaxYearStatus,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_tax_year(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in TaxYearStatus]
    assert isinstance(data["fiscal_year_label"], str)
    assert isinstance(data["enacted_federal_rate_bp"], int)
    assert isinstance(data["pretax_book_income_cents"], int)
    assert isinstance(data["prior_year_total_tax_cents"], int)
    for field in ("current_provision_cents", "deferred_expense_cents",
                  "net_deferred_asset_cents", "valuation_allowance_cents",
                  "utp_liability_cents",
                  "return_to_provision_adjustment_cents",
                  "forecast_etr_bp", "actual_etr_bp"):
        assert isinstance(data[field], int), f"{field} must be integer cents/bp"


def assert_jurisdiction(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["level"] in [lv.value for lv in JurisdictionLevel]
    assert 0 <= data["statutory_rate_bp"] <= 10000
    assert 0 <= data["apportionment_pct_bp"] <= 10000
    assert 1 <= data["return_due_month"] <= 12
    assert 1 <= data["return_due_day"] <= 31


def assert_book_tax_difference(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in DifferenceStatus]
    assert data["difference_type"] in [t.value for t in DifferenceType]
    assert isinstance(data["book_amount_cents"], int)
    assert isinstance(data["tax_amount_cents"], int)
    assert isinstance(data["difference_cents"], int)
    # PRD: difference_cents = book_amount_cents - tax_amount_cents
    assert data["difference_cents"] == (
        data["book_amount_cents"] - data["tax_amount_cents"]
    ), "difference_cents must equal book minus tax"


def assert_deferred_tax_item(data: dict):
    _assert_common(data)
    assert data["item_kind"] in [k.value for k in DeferredItemKind]
    assert isinstance(data["movement_cents"], int)
    assert data["movement_cents"] >= 0, "movement is a nonnegative magnitude"
    assert isinstance(data["opening_balance_cents"], int)
    assert isinstance(data["closing_balance_cents"], int)


def assert_rollforward_invariant(item: dict):
    """PRD §3.2: opening plus movement equals closing, always."""
    assert item["closing_balance_cents"] == (
        item["opening_balance_cents"] + item["movement_cents"]
    ), "rollforward invariant violated: opening + movement != closing"


def assert_valuation_allowance(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in AllowanceStatus]
    assert isinstance(data["more_likely_than_not"], bool)
    assert isinstance(data["allowance_amount_cents"], int)
    assert data["allowance_amount_cents"] >= 0
    assert isinstance(data["prepared_by_user_id"], str)


def assert_uncertain_tax_position(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in PositionStatus]
    assert isinstance(data["position_amount_cents"], int)
    assert data["position_amount_cents"] > 0
    assert isinstance(data["recognized_benefit_cents"], int)
    assert isinstance(data["liability_cents"], int)
    assert isinstance(data["disclosure_required"], bool)
    assert isinstance(data["interest_accrued_cents"], int)


def assert_estimated_payment(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in PaymentStatus]
    assert data["method"] in [m.value for m in PaymentMethod]
    assert data["quarter_index"] in (1, 2, 3, 4)
    assert isinstance(data["scheduled_amount_cents"], int)
    assert isinstance(data["base_scheduled_amount_cents"], int)
    assert isinstance(data["paid_amount_cents"], int)
    assert data["paid_amount_cents"] >= 0
    assert isinstance(data["penalty_cents"], int)
    assert data["penalty_cents"] >= 0


def assert_filing(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in FilingStatus]
    assert data["extension_status"] in [s.value for s in ExtensionStatus]
    assert isinstance(data["original_due_date"], str)


def assert_tax_notice(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in NoticeStatus]
    assert data["notice_type"] in [t.value for t in NoticeType]
    assert isinstance(data["received_on"], str)
    assert isinstance(data["response_due_on"], str)


def assert_audit_case(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in AuditStatus]
    assert isinstance(data["exam_period_start"], str)
    assert isinstance(data["exam_period_end"], str)
    assert data["exam_period_end"] > data["exam_period_start"], \
        "half-open exam period end must be after start"
