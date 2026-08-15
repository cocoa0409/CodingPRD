"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

Each assert_* validates the fields the PRD names for that resource: identity
and audit fields plus the domain fields tests rely on. The three ledger-entry
resources (AFUDC / depreciation / amortization) are append-only and per
PRD §2.4 carry only id and created_at — no updated_at, no version.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """PRD §2.4: ledger entries carry only id and created_at (no updated_at,
    no version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"


def assert_capital_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["authorized_amount_cents"], int)
    assert data["afudc_method"] in ("HALF_MONTH", "FULL_MONTH")
    assert data["ciac_method"] in ("NET_OF_CIAC", "GROSS_WITH_CONTRA")
    assert data["status"] in ("OPEN", "CLOSED")
    for field in ("committed_amount_cents", "capitalized_actual_cents",
                  "expense_writeoff_cents", "ciac_contra_balance_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_unit_catalog_entry(data: dict):
    _assert_common_fields(data)
    assert data["asset_class"] in ("POLE", "TRANSFORMER", "CONDUCTOR", "METER",
                                   "REGULATOR")
    assert isinstance(data["standard_cost_cents"], int)
    assert data["standard_cost_cents"] >= 0


def assert_overhead_schedule(data: dict):
    _assert_common_fields(data)
    assert data["cost_type"] in ("LABOR", "EQUIPMENT", "MATERIAL")
    assert data["order_type"] in ("CAPITAL", "EXPENSE")
    assert data["status"] == "ACTIVE"


def assert_accounting_period(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["period_no"], int) and data["period_no"] >= 1
    assert data["status"] in ("OPEN", "CLOSED", "REOPENED")


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert data["order_type"] in ("CAPITAL", "EXPENSE")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "RETURNED", "AUTHORIZED", "IN_PROGRESS",
        "SUSPENDED", "COMPLETED", "CLOSED", "CANCELLED")
    assert data["variance_posture"] in ("WITHIN_TOLERANCE",
                                        "RE_ESTIMATE_REQUIRED")
    assert isinstance(data["estimate_seq"], int) and data["estimate_seq"] >= 1
    for field in ("actual_direct_cents", "afudc_total_cents", "cwip_cents",
                  "ciac_applied_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data["created_by_user_id"], str)


def assert_estimate(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["estimate_seq"], int) and data["estimate_seq"] >= 1
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["status"] in ("PROPOSED", "APPROVED", "SUPERSEDED", "REJECTED",
                              "WITHDRAWN")
    assert isinstance(data["submitted_by_user_id"], str)


def assert_cost_charge(data: dict):
    _assert_common_fields(data)
    assert data["cost_type"] in ("LABOR", "EQUIPMENT", "MATERIAL")
    assert data["kind"] in ("ORIGINAL", "REVERSAL")
    assert data["status"] in ("POSTED", "REVERSED")
    for field in ("base_amount_cents", "overhead_amount_cents", "total_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data["posted_by_user_id"], str)


def assert_ciac_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["pledged_cents"], int) and data["pledged_cents"] > 0
    assert data["status"] in ("PLEDGED", "RECEIVED", "APPLIED", "REFUNDED",
                              "EXPIRED", "CANCELLED")


def assert_fixed_asset_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["line_no"], int) and data["line_no"] >= 0
    assert isinstance(data["allocated_cost_cents"], int)
    assert isinstance(data["accumulated_depreciation_cents"], int)
    assert data["status"] in ("IN_SERVICE", "RETIRED")


def assert_regulatory_asset(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["original_cents"], int) and data["original_cents"] > 0
    assert isinstance(data["amortization_months"], int) \
        and data["amortization_months"] >= 1
    assert isinstance(data["remaining_cents"], int)
    assert data["status"] in ("PROPOSED", "APPROVED", "AMORTIZING", "REJECTED",
                              "FULLY_AMORTIZED")
    assert isinstance(data["proposed_by_user_id"], str)


def assert_afudc_entry(data: dict):
    _assert_append_only_fields(data)
    assert "updated_at" not in data, "append-only entries have no updated_at"
    assert "version" not in data, "append-only entries have no version"
    assert data["method"] in ("HALF_MONTH", "FULL_MONTH")
    assert isinstance(data["base_cents"], int)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("ACCRUED", "REVERSED")


def assert_depreciation_entry(data: dict):
    _assert_append_only_fields(data)
    assert "updated_at" not in data, "append-only entries have no updated_at"
    assert "version" not in data, "append-only entries have no version"
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["ciac_contra_credit_cents"], int)
    assert data["status"] in ("POSTED", "REVERSED")


def assert_amortization_entry(data: dict):
    _assert_append_only_fields(data)
    assert "updated_at" not in data, "append-only entries have no updated_at"
    assert "version" not in data, "append-only entries have no version"
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("POSTED", "REVERSED")


def assert_work_order_ledger_invariants(wo: dict):
    """PRD §3.5: cwip_cents is always actual_direct_cents + afudc_total_cents;
    AFUDC is excluded from the variance base."""
    assert wo["cwip_cents"] == wo["actual_direct_cents"] + wo["afudc_total_cents"], (
        f"cwip_cents {wo['cwip_cents']} != actual_direct_cents "
        f"{wo['actual_direct_cents']} + afudc_total_cents {wo['afudc_total_cents']}")


def assert_program_budget_invariants(program: dict):
    """PRD §3.3: available_amount_cents is always authorized minus committed."""
    assert (program["available_amount_cents"]
            == program["authorized_amount_cents"]
            - program["committed_amount_cents"]), (
        "available_amount_cents must equal authorized minus committed")
