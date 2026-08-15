"""Entity assertions and domain invariant checkers.

Each assert_* checks the PRD's common resource properties (id, created_at,
updated_at, version — PRD 2.5) plus status-enum membership. Nullable fields
are type-checked only when present and non-null, so a faithful serializer that
omits nulls still passes.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version must be >= 1"


def _assert_optional_str(data: dict, field: str, label: str):
    if field in data and data[field] is not None:
        assert isinstance(data[field], str), f"{label}.{field} must be a string"


def _assert_optional_int(data: dict, field: str, label: str):
    if field in data and data[field] is not None:
        assert isinstance(data[field], int), f"{label}.{field} must be an integer"


def assert_jurisdiction(data: dict):
    _assert_common(data, "Jurisdiction")
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["rush_daily_capacity"], int)


def assert_statute(data: dict):
    _assert_common(data, "JurisdictionStatute")
    assert isinstance(data["jurisdiction_id"], str)
    assert isinstance(data["effective_from"], str)
    _assert_optional_str(data, "effective_to", "JurisdictionStatute")
    assert isinstance(data["estoppel_response_days"], int)
    assert isinstance(data["estoppel_fee_cap_cents"], int)
    assert isinstance(data["estoppel_validity_days"], int)


def assert_department(data: dict):
    _assert_common(data, "Department")
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert data["dept_type"] in ("UTILITY", "CODE_ENFORCEMENT", "PERMIT", "TAX_COLLECTOR")
    assert isinstance(data["research_fee_cents"], int)


def assert_association(data: dict):
    _assert_common(data, "Association")
    assert isinstance(data["jurisdiction_id"], str)
    assert isinstance(data["estoppel_fee_cents"], int)
    assert isinstance(data["estoppel_validity_days"], int)


def assert_search_order(data: dict):
    _assert_common(data, "SearchOrder")
    assert data["status"] in (
        "INTAKE",
        "RESEARCH_IN_PROGRESS",
        "VERIFICATION",
        "READY_FOR_DELIVERY",
        "DELIVERED",
        "CANCELLED",
    )
    assert isinstance(data["parcel_number"], str) and data["parcel_number"]
    assert data["order_class"] in ("STANDARD", "RUSH")
    assert isinstance(data["title_agent_id"], str) and data["title_agent_id"]
    for field in (
        "total_payoff_cents",
        "total_fees_cents",
        "pending_claims_cents",
        "total_liability_cents",
    ):
        assert isinstance(data[field], int), f"SearchOrder.{field} must be integer cents"
        assert data[field] >= 0, f"SearchOrder.{field} must be non-negative"
    _assert_optional_str(data, "jurisdiction_id", "SearchOrder")
    _assert_optional_str(data, "statute_id", "SearchOrder")
    _assert_optional_str(data, "association_id", "SearchOrder")
    _assert_optional_str(data, "service_date", "SearchOrder")
    _assert_optional_str(data, "payoff_verified_by_user_id", "SearchOrder")


def assert_research_task(data: dict):
    _assert_common(data, "ResearchTask")
    assert data["status"] in (
        "PENDING",
        "IN_PROGRESS",
        "COMPLETED",
        "UNABLE_TO_REACH",
        "CANCELLED",
    )
    assert isinstance(data["search_order_id"], str)
    assert isinstance(data["department_id"], str)
    assert data["dept_type"] in ("UTILITY", "CODE_ENFORCEMENT", "PERMIT", "TAX_COLLECTOR")
    assert isinstance(data["unpaid_balance_cents"], int)
    assert isinstance(data["open_violation_count"], int)
    assert isinstance(data["fee_base_cents"], int)
    assert isinstance(data["fee_charged_cents"], int)
    _assert_optional_str(data, "unreachable_reason", "ResearchTask")
    _assert_optional_str(data, "completed_by_user_id", "ResearchTask")


def assert_estoppel_order(data: dict):
    _assert_common(data, "EstoppelOrder")
    assert data["status"] in (
        "DRAFT",
        "ORDERED",
        "OVERDUE",
        "RECEIVED",
        "EXPIRED",
        "CANCELLED",
    )
    assert isinstance(data["search_order_id"], str)
    assert isinstance(data["association_id"], str)
    assert isinstance(data["renewal_count"], int)
    _assert_optional_int(data, "fee_quoted_cents", "EstoppelOrder")
    _assert_optional_str(data, "statutory_due_at", "EstoppelOrder")
    _assert_optional_str(data, "valid_through", "EstoppelOrder")


def assert_discrepancy(data: dict):
    _assert_common(data, "Discrepancy")
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "RESOLVED")
    assert data["subject_type"] in ("SEARCH_ORDER", "RESEARCH_TASK", "ESTOPPEL_ORDER")
    assert data["discrepancy_type"] in (
        "MISSED_ITEM",
        "BALANCE_MISMATCH",
        "PAYOFF_MISMATCH",
        "STALE_ESTOPPEL",
    )
    assert isinstance(data["claimed_amount_cents"], int)
    assert isinstance(data["filed_by_user_id"], str)
    _assert_optional_str(data, "resolution_outcome", "Discrepancy")


def assert_delivery(data: dict):
    _assert_common(data, "Delivery")
    assert data["status"] in (
        "READY",
        "DELIVERED",
        "ACKNOWLEDGED",
        "SUPERSEDED",
        "VOIDED",
    )
    assert isinstance(data["search_order_id"], str)
    _assert_optional_str(data, "delivered_to_agent_id", "Delivery")


def assert_order_totals_invariants(order: dict):
    """Domain invariants that must hold on any SearchOrder read."""
    assert order["total_payoff_cents"] >= 0
    assert order["total_fees_cents"] >= 0
    assert order["pending_claims_cents"] >= 0
    assert order["total_liability_cents"] >= 0
