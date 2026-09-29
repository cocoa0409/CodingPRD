"""Entity assertions and ledger invariants for the Custom Home Builder API."""

from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import MONEY_TOLERANCE


# ─── Primitive helpers ────────────────────────────────────────────────────
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant carried by the API."""
    assert isinstance(value, str) and value, f"Expected an ISO 8601 instant, got {value!r}"
    normalised = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalised)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual, expected_iso: str, label: str = "timestamp") -> None:
    """Assert an API instant equals the expected ISO 8601 UTC instant."""
    assert actual is not None, f"{label} must not be null (expected {expected_iso})"
    assert is_iso8601_timestamp(actual), (
        f"{label} must be an ISO 8601 UTC timestamp, got {actual!r}"
    )
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected {expected_iso}, got {actual}"
    )


def assert_money_equals(actual, expected: float, label: str = "amount") -> None:
    """Assert a money field carries the expected two-decimal value."""
    assert actual is not None, f"{label} must not be null (expected {expected})"
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be numeric, got {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )
    assert_cost_precision(float(actual))


def assert_money_not_equals(actual, wrong: float, label: str = "amount") -> None:
    """Assert a money field is not the value a mis-ordered rounding would give."""
    assert abs(float(actual) - wrong) > MONEY_TOLERANCE, (
        f"{label}: {actual} matches the incorrect value {wrong}"
    )


def _assert_common_fields(data: dict, entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a bare UUID with no type prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and not isinstance(
        data.get("version"), bool
    ), f"{entity}.version must be an integer, got {data.get('version')!r}"
    assert data["version"] >= 1, f"{entity}.version starts at 1, got {data['version']}"


# ─── Reference parties ────────────────────────────────────────────────────
def assert_client(data: dict) -> None:
    _assert_common_fields(data, "Client")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["portal_enabled"], bool)


def assert_lender(data: dict) -> None:
    _assert_common_fields(data, "Lender")
    assert isinstance(data["name"], str) and data["name"]
    assert 0 <= data["retainage_pct"] <= 0.20
    assert 0 < data["max_cumulative_draw_pct"] <= 1
    assert isinstance(data["review_window_days"], int) and data["review_window_days"] >= 1


def assert_staff_member(data: dict) -> None:
    _assert_common_fields(data, "StaffMember")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["staff_function"] in ("PROJECT_MANAGER", "ESTIMATOR", "CONTROLLER")


def assert_subcontractor(data: dict) -> None:
    _assert_common_fields(data, "Subcontractor")
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert data["trade"] in (
        "SITEWORK",
        "CONCRETE",
        "FRAMING",
        "PLUMBING",
        "ELECTRICAL",
        "HVAC",
        "DRYWALL",
        "FINISH_CARPENTRY",
        "PAINT",
        "LANDSCAPE",
    )
    assert isinstance(data["lead_time_days"], int) and data["lead_time_days"] >= 0
    assert isinstance(data["crew_capacity"], int) and data["crew_capacity"] >= 1
    assert isinstance(data["waiver_required"], bool)


# ─── Project ──────────────────────────────────────────────────────────────
def assert_project(data: dict) -> None:
    _assert_common_fields(data, "Project")
    assert isinstance(data["client_id"], str) and data["client_id"]
    assert isinstance(data["address"], str) and data["address"]
    assert data["contract_type"] in ("FIXED_PRICE", "COST_PLUS")
    assert data["status"] in (
        "PLANNING",
        "UNDER_CONSTRUCTION",
        "SUBSTANTIAL_COMPLETION",
        "FINAL_ACCEPTED",
    )
    assert data["budget_posture"] in ("WITHIN_BUDGET", "ALLOWANCE_OVERRUN", "OVER_GMP")
    assert data["base_contract_amount"] > 0
    for money_field in (
        "base_contract_amount",
        "approved_change_order_total",
        "allowance_variance_total",
        "contract_sum_current",
        "cost_to_date",
        "eligible_cost_pool",
        "pending_draw_amount",
        "funded_to_date",
        "retainage_held",
    ):
        assert isinstance(data[money_field], (int, float)), (
            f"Project.{money_field} must be numeric, got {data.get(money_field)!r}"
        )
        assert_cost_precision(float(data[money_field]))


def assert_project_ledger_invariants(data: dict) -> None:
    """Ledger identities that must hold on a project after any operation."""
    assert data["cost_to_date"] >= 0
    assert data["eligible_cost_pool"] >= 0
    assert data["pending_draw_amount"] >= 0
    assert data["funded_to_date"] >= 0
    assert data["retainage_held"] >= 0
    assert data["eligible_cost_pool"] <= data["cost_to_date"] + MONEY_TOLERANCE, (
        "eligible_cost_pool is the narrower pool and can never exceed cost_to_date"
    )
    expected_sum = (
        data["base_contract_amount"]
        + data["approved_change_order_total"]
        + data["allowance_variance_total"]
    )
    assert data["contract_sum_current"] == pytest.approx(expected_sum, abs=MONEY_TOLERANCE), (
        "contract_sum_current must equal base_contract_amount + "
        "approved_change_order_total + allowance_variance_total"
    )


# ─── Allowance book ───────────────────────────────────────────────────────
def assert_allowance_item(data: dict) -> None:
    _assert_common_fields(data, "AllowanceItem")
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert data["category"] in (
        "FLOORING",
        "CABINETRY",
        "APPLIANCES",
        "PLUMBING_FIXTURES",
        "LIGHTING",
        "COUNTERTOPS",
        "LANDSCAPE",
    )
    assert data["allowance_amount"] > 0
    assert_cost_precision(float(data["allowance_amount"]))
    assert data["status"] in ("OPEN", "FROZEN", "SELECTED", "LOCKED", "RECONCILED")
    assert is_iso8601_timestamp(data["selection_deadline"])
    assert isinstance(data["provisional_variance_amount"], (int, float))


def assert_selection(data: dict) -> None:
    _assert_common_fields(data, "Selection")
    assert isinstance(data["allowance_item_id"], str) and data["allowance_item_id"]
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert data["vendor_quote_amount"] >= 0
    assert data["freight_amount"] >= 0
    assert data["install_amount"] >= 0
    assert isinstance(data["lead_time_days"], int) and data["lead_time_days"] >= 0
    assert data["status"] in ("PROPOSED", "ACCEPTED", "REJECTED", "SUPERSEDED")
    assert_money_equals(
        data["selection_total"],
        float(data["vendor_quote_amount"])
        + float(data["freight_amount"])
        + float(data["install_amount"]),
        "Selection.selection_total",
    )


# ─── Change orders ────────────────────────────────────────────────────────
def assert_change_order(data: dict) -> None:
    _assert_common_fields(data, "ChangeOrder")
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert data["origin"] in ("CLIENT_REQUEST", "FIELD_CONDITION", "ALLOWANCE_OVERAGE")
    assert isinstance(data["scope_description"], str) and data["scope_description"]
    assert data["direct_cost"] >= 0
    assert_cost_precision(float(data["direct_cost"]))
    assert isinstance(data["schedule_impact_days"], int) and data["schedule_impact_days"] >= 0
    assert data["status"] in (
        "DRAFT",
        "PRICED",
        "SUBMITTED",
        "REVISION_REQUESTED",
        "APPROVED",
        "REJECTED",
        "VOIDED",
    )
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    if data.get("priced_amount") is not None:
        assert_cost_precision(float(data["priced_amount"]))


# ─── Schedule ─────────────────────────────────────────────────────────────
def assert_schedule_task(data: dict) -> None:
    _assert_common_fields(data, "ScheduleTask")
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert isinstance(data["subcontractor_id"], str) and data["subcontractor_id"]
    assert isinstance(data["task_name"], str) and data["task_name"]
    assert is_iso8601_timestamp(data["planned_start"])
    assert is_iso8601_timestamp(data["planned_finish"])
    assert parse_instant(data["planned_finish"]) > parse_instant(data["planned_start"]), (
        "planned_finish must be strictly later than planned_start"
    )
    assert data["status"] in ("PLANNED", "RELEASED", "IN_PROGRESS", "COMPLETE")
    assert isinstance(data["lag_days"], int) and data["lag_days"] >= 0
    assert isinstance(data["exclusive_use"], bool)
    assert isinstance(data["delay_days"], int) and data["delay_days"] >= 0


# ─── Cost and draws ───────────────────────────────────────────────────────
def assert_cost_entry(data: dict) -> None:
    _assert_common_fields(data, "CostEntry")
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert data["entry_type"] in (
        "SUBCONTRACT_INVOICE",
        "MATERIAL",
        "LABOR",
        "ALLOWANCE_ACTUAL",
        "CHANGE_ORDER_WORK",
    )
    assert isinstance(data["cost_code"], str) and data["cost_code"]
    assert data["amount"] > 0
    assert_cost_precision(float(data["amount"]))
    assert is_iso8601_timestamp(data["incurred_at"])
    assert data["status"] in (
        "PENDING",
        "APPROVED",
        "REJECTED",
        "INCLUDED_IN_DRAW",
        "PAID",
    )


def assert_draw_request(data: dict) -> None:
    _assert_common_fields(data, "DrawRequest")
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert parse_instant(data["period_end"]) > parse_instant(data["period_start"])
    assert data["status"] in (
        "DRAFT",
        "LENDER_REVIEW",
        "CONDITIONALLY_APPROVED",
        "RETURNED",
        "FUNDED",
        "VOIDED",
    )
    assert data["waiver_compliance"] in ("PENDING", "PARTIAL", "COMPLETE")
    for money_field in ("requested_amount", "retainage_amount", "net_funding_amount"):
        assert isinstance(data[money_field], (int, float))
        assert_cost_precision(float(data[money_field]))
    for count_field in (
        "included_cost_entry_count",
        "required_waiver_count",
        "verified_waiver_count",
    ):
        assert isinstance(data[count_field], int) and data[count_field] >= 0
    assert data["verified_waiver_count"] <= data["required_waiver_count"]


def assert_draw_funding_arithmetic(data: dict) -> None:
    """net_funding_amount is requested_amount minus retainage_amount."""
    assert_money_equals(
        data["net_funding_amount"],
        float(data["requested_amount"]) - float(data["retainage_amount"]),
        "DrawRequest.net_funding_amount",
    )


def assert_lien_waiver(data: dict) -> None:
    _assert_common_fields(data, "LienWaiver")
    assert isinstance(data["draw_request_id"], str) and data["draw_request_id"]
    assert isinstance(data["subcontractor_id"], str) and data["subcontractor_id"]
    assert data["required_waiver_type"] in (
        "CONDITIONAL_PROGRESS",
        "UNCONDITIONAL_PROGRESS",
        "CONDITIONAL_FINAL",
        "UNCONDITIONAL_FINAL",
    )
    assert data["required_amount"] >= 0
    assert_cost_precision(float(data["required_amount"]))
    assert data["status"] in ("REQUESTED", "RECEIVED", "VERIFIED", "REJECTED", "VOIDED")
    assert isinstance(data["resubmit_count"], int) and data["resubmit_count"] >= 0


# ─── Punch list and warranty ──────────────────────────────────────────────
def assert_defect_ticket(data: dict) -> None:
    _assert_common_fields(data, "DefectTicket")
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert data["phase"] in ("PUNCH", "WARRANTY")
    assert isinstance(data["room"], str) and data["room"]
    assert isinstance(data["description"], str) and data["description"]
    assert data["severity"] in ("COSMETIC", "FUNCTIONAL", "LIFE_SAFETY")
    assert data["category"] in (
        "WORKMANSHIP",
        "MATERIAL_DEFECT",
        "SYSTEMS",
        "HOMEOWNER_DAMAGE",
        "NORMAL_WEAR",
    )
    assert is_iso8601_timestamp(data["reported_at"])
    assert data["coverage_anchor"] in ("NONE", "WHOLE_HOUSE", "TRADE")
    assert data["coverage_result"] in (
        "NOT_APPLICABLE",
        "COVERED",
        "OUT_OF_COVERAGE",
        "EXCLUDED",
    )
    assert data["status"] in (
        "OPEN",
        "ASSIGNED",
        "READY_FOR_REVIEW",
        "VERIFIED",
        "REJECTED",
        "DENIED",
        "WAIVED",
    )
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0


def assert_photo_document(data: dict) -> None:
    _assert_common_fields(data, "PhotoDocument")
    assert is_iso8601_timestamp(data["captured_at"])
    assert isinstance(data["caption"], str)
    assert data["visibility"] in ("INTERNAL", "CLIENT_PORTAL")
