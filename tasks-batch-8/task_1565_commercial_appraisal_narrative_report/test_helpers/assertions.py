"""Entity assertions and domain invariant checkers (PRD §2.5, §3).

Each assert_* validates the common fields (id, created_at, updated_at,
version) plus the entity's status enum membership. Nullable system fields are
type-checked only when present and non-null, so a serializer that omits a
null field stays conforming.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_timestamp_prefix(value, prefix: str):
    """A logical-clock timestamp must carry the exact date-time prefix.

    PRD §2.4 pins the clock reading; PRD §2.5 renders timestamps as ISO 8601
    UTC with fractional digits, so equality is asserted on the shared prefix
    rather than on the fractional-second rendering.
    """
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    assert value.startswith(prefix), f"expected {value!r} to start with {prefix!r}"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["client_type"] in ["LENDER", "LAW_FIRM", "INVESTOR", "GOVERNMENT_AGENCY"]
    assert isinstance(data["total_billed_cents"], int)
    assert data["volume_discount_tier"] in ["NONE", "TIER_1", "TIER_2"]


def assert_appraiser(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["designation"] in ["TRAINEE", "CERTIFIED_GENERAL", "MAI"]
    assert data["license_status"] in ["ACTIVE", "SUSPENDED", "EXPIRED"]


def assert_engagement(data: dict):
    _assert_common(data)
    for fk in ("client_id", "author_appraiser_id", "reviewer_appraiser_id"):
        assert is_valid_uuid(data.get(fk, "")), f"{fk} must be a UUID"
    assert data["property_type"] in [
        "OFFICE", "RETAIL", "INDUSTRIAL", "MULTIFAMILY", "SPECIAL_PURPOSE",
    ]
    assert data["intended_use"] in [
        "FINANCING", "LITIGATION", "FINANCIAL_REPORTING", "TAX_APPEAL",
    ]
    assert isinstance(data["building_sf"], int) and data["building_sf"] > 0
    assert isinstance(data["requested_turnaround_days"], int)
    assert data["requested_turnaround_days"] > 0
    assert data["planned_approach_count"] in (1, 2, 3)
    assert data["complexity_tier"] in ["LOW", "STANDARD", "HIGH"]
    assert isinstance(data["minimum_turnaround_days"], int)
    assert data["status"] in [
        "DRAFT", "PENDING_ACCEPTANCE", "IN_PROGRESS", "LITIGATION_HOLD",
        "COMPLETED", "CANCELLED", "DECLINED", "EXPIRED",
    ]
    if data.get("quoted_fee_cents") is not None:
        assert isinstance(data["quoted_fee_cents"], int)
    if data.get("final_fee_cents") is not None:
        assert isinstance(data["final_fee_cents"], int)


def assert_data_submission(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("engagement_id", ""))
    assert data["submission_type"] in ["RENT_ROLL", "OPERATING_STATEMENT", "TAX_BILL"]
    for money in ("scheduled_gross_rent_cents", "vacancy_loss_cents",
                  "expense_reimbursements_cents", "operating_expenses_cents"):
        assert isinstance(data[money], int) and data[money] >= 0
    assert data["status"] in ["SUBMITTED", "ACCEPTED", "REJECTED", "LOCKED"]
    if data.get("noi_trailing_cents") is not None:
        assert isinstance(data["noi_trailing_cents"], int)
    if data.get("noi_stabilized_cents") is not None:
        assert isinstance(data["noi_stabilized_cents"], int)


def assert_approach(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("engagement_id", ""))
    assert data["approach_type"] in ["INCOME", "SALES_COMPARISON", "COST"]
    assert data["status"] in ["SELECTED", "COMPLETE", "EXCLUDED"]
    assert isinstance(data["weight_pct"], (int, float))
    assert 0 <= data["weight_pct"] <= 100
    if data.get("indicated_value_cents") is not None:
        assert isinstance(data["indicated_value_cents"], int)


def assert_comparable(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("engagement_id", ""))
    assert isinstance(data["address"], str) and data["address"]
    assert isinstance(data["sale_price_cents"], int) and data["sale_price_cents"] > 0
    assert isinstance(data["noi_at_sale_cents"], int) and data["noi_at_sale_cents"] > 0
    assert isinstance(data["size_sf"], int) and data["size_sf"] > 0
    if data.get("implied_cap_rate_bps") is not None:
        assert isinstance(data["implied_cap_rate_bps"], int)
    if data.get("adjusted_cap_rate_bps") is not None:
        assert isinstance(data["adjusted_cap_rate_bps"], int)


def assert_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("engagement_id", ""))
    assert isinstance(data["report_version_no"], int) and data["report_version_no"] >= 1
    assert data["status"] in [
        "DRAFTING", "INTERNAL_REVIEW", "REVIEWED", "CLIENT_REVIEW",
        "REVISION_REQUESTED", "FINAL", "SIGNED", "DELIVERED",
        "SUPERSEDED", "SUSPENDED",
    ]
    if data.get("value_conclusion_cents") is not None:
        assert isinstance(data["value_conclusion_cents"], int)
    if data.get("review_cycle_count") is not None:
        assert isinstance(data["review_cycle_count"], int)


def assert_revision_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("report_id", ""))
    assert data["category"] in [
        "FACTUAL_CORRECTION", "CLARIFICATION", "METHODOLOGY_QUESTION", "VALUE_PRESSURE",
    ]
    assert isinstance(data["requested_change"], str)
    assert data["status"] in ["OPEN", "ACCEPTED", "DECLINED", "ESCALATED", "WITHDRAWN"]


def assert_retention_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("engagement_id", ""))
    assert data["status"] in [
        "ACTIVE", "LITIGATION_HOLD", "RELEASED_PENDING_DESTRUCTION", "DESTROYED",
    ]
    if data.get("retain_until_date") is not None:
        assert isinstance(data["retain_until_date"], str)
    if data.get("base_retain_until_date") is not None:
        assert isinstance(data["base_retain_until_date"], str)
