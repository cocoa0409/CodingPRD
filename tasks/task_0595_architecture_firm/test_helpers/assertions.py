"""Entity assertions and domain invariant checkers for the Architecture Firm API."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    ProjectStatus, ContractStatus, PhaseStatus, PhaseCode, MilestoneStatus,
    DrawingStatus, TimeEntryStatus, ExpenseStatus, RfiStatus, RfiOrigin,
    SubmittalStatus, ChangeOrderStatus, InvoiceStatus, PaymentStatus,
    PermitReviewStatus, BudgetPosture, CaPosture, FeeBasis, ReviewClockBasis,
    ConsultantFirmStatus, StaffTitle, Discipline, ExpenseCategory,
    ChangeOrderType, PermitType,
)


# --------------------------------------------------------------------------- #
# Timestamp helpers
# --------------------------------------------------------------------------- #
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant. Tolerates 'Z' and any fractional-second precision."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected: str, label: str = "instant"):
    """Compare two ISO 8601 instants by value, not by serialised spelling."""
    assert actual is not None, f"{label} must not be null"
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, f"{label}: expected {expected}, got {actual}"


# --------------------------------------------------------------------------- #
# Common-field checks
# --------------------------------------------------------------------------- #
def _assert_versioned_common_fields(data: dict, entity: str):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_append_only_common_fields(data: dict, entity: str = "FieldReport"):
    """id + created_at ONLY — no updated_at, no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} must not serialise an updated_at key"
    assert "version" not in data, f"{entity} must not serialise a version key"


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


# --------------------------------------------------------------------------- #
# Per-entity assertions
# --------------------------------------------------------------------------- #
def assert_staff_member(data: dict):
    _assert_versioned_common_fields(data, "StaffMember")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["title"] in _enum_values(StaffTitle)
    assert isinstance(data["billing_rate_cents_per_hour"], int) and data["billing_rate_cents_per_hour"] > 0
    assert isinstance(data["cost_rate_cents_per_hour"], int) and data["cost_rate_cents_per_hour"] > 0
    assert isinstance(data["active"], bool)


def assert_consultant_firm(data: dict):
    _assert_versioned_common_fields(data, "ConsultantFirm")
    assert isinstance(data["name"], str) and data["name"]
    assert data["discipline"] in _enum_values(Discipline)
    assert isinstance(data["concurrent_review_capacity"], int) and data["concurrent_review_capacity"] >= 1
    assert data["status"] in _enum_values(ConsultantFirmStatus)


def assert_project(data: dict):
    _assert_versioned_common_fields(data, "Project")
    assert isinstance(data["project_number"], str) and data["project_number"]
    assert isinstance(data["name"], str)
    assert isinstance(data["client_rep_user_id"], str)
    assert isinstance(data["project_manager_staff_id"], str)
    assert data["status"] in _enum_values(ProjectStatus)
    assert isinstance(data["labor_budget_cents"], int) and data["labor_budget_cents"] > 0
    assert isinstance(data["labor_cost_cents"], int) and data["labor_cost_cents"] >= 0
    assert isinstance(data["approved_hours"], (int, float)) and data["approved_hours"] >= 0
    assert data["budget_posture"] in _enum_values(BudgetPosture)
    assert isinstance(data["open_rfi_count"], int) and data["open_rfi_count"] >= 0
    assert data["ca_posture"] in _enum_values(CaPosture)
    assert_project_posture_invariants(data)


def assert_project_posture_invariants(data: dict):
    """PRD §3.4: budget_posture and ca_posture are pure functions of their inputs."""
    expected_budget = (
        BudgetPosture.OVER_BUDGET.value
        if data["labor_cost_cents"] >= data["labor_budget_cents"]
        else BudgetPosture.WITHIN_BUDGET.value
    )
    assert data["budget_posture"] == expected_budget, (
        f"budget_posture must be {expected_budget} when labor_cost_cents="
        f"{data['labor_cost_cents']} and labor_budget_cents={data['labor_budget_cents']}"
    )
    expected_ca = (
        CaPosture.DEFICIENT.value if data["open_rfi_count"] > 0 else CaPosture.CLEAR.value
    )
    assert data["ca_posture"] == expected_ca, (
        f"ca_posture must be {expected_ca} when open_rfi_count={data['open_rfi_count']}"
    )


def assert_contract(data: dict):
    _assert_versioned_common_fields(data, "Contract")
    assert isinstance(data["project_id"], str)
    assert data["fee_basis"] in _enum_values(FeeBasis)
    assert data["review_clock_basis"] in _enum_values(ReviewClockBasis)
    assert isinstance(data["submittal_review_period_days"], int) and data["submittal_review_period_days"] >= 1
    assert data["status"] in _enum_values(ContractStatus)
    for field in (
        "base_fee_cents", "total_fee_cents", "earned_to_date_cents",
        "billed_fee_to_date_cents", "wip_balance_cents",
    ):
        assert isinstance(data[field], int), f"Contract.{field} must be an integer number of cents"
    assert_contract_wip_identity(data)


def assert_contract_wip_identity(data: dict):
    """PRD §2.6: wip_balance_cents is always earned_to_date_cents - billed_fee_to_date_cents."""
    expected = data["earned_to_date_cents"] - data["billed_fee_to_date_cents"]
    assert data["wip_balance_cents"] == expected, (
        "wip_balance_cents must equal earned_to_date_cents - billed_fee_to_date_cents "
        f"({data['earned_to_date_cents']} - {data['billed_fee_to_date_cents']} = {expected}), "
        f"got {data['wip_balance_cents']}"
    )


def assert_phase(data: dict):
    _assert_versioned_common_fields(data, "Phase")
    assert isinstance(data["project_id"], str)
    assert data["phase_code"] in _enum_values(PhaseCode)
    assert isinstance(data["phase_order"], int) and 1 <= data["phase_order"] <= 4
    assert isinstance(data["weight_bp"], int) and 0 <= data["weight_bp"] <= 10_000
    assert data["status"] in _enum_values(PhaseStatus)
    assert isinstance(data["percent_complete"], int) and 0 <= data["percent_complete"] <= 100
    assert isinstance(data["fee_allocation_cents"], int)
    assert isinstance(data["earned_cents"], int)
    assert isinstance(data["milestone_name"], str)
    assert data["milestone_status"] in _enum_values(MilestoneStatus)
    assert isinstance(data["is_billing_milestone"], bool)


def assert_phase_allocation_sums_to_total(phases: list, total_fee_cents: int):
    """PRD §2.9: the four phases' fee_allocation_cents always sum to exactly total_fee_cents."""
    total = sum(p["fee_allocation_cents"] for p in phases)
    assert total == total_fee_cents, (
        f"phase fee_allocation_cents must sum to total_fee_cents {total_fee_cents}, got {total}"
    )


def assert_drawing(data: dict):
    _assert_versioned_common_fields(data, "Drawing")
    assert isinstance(data["phase_id"], str)
    assert isinstance(data["sheet_number"], str) and data["sheet_number"]
    assert isinstance(data["title"], str)
    assert isinstance(data["revision"], int) and data["revision"] >= 0
    assert data["status"] in _enum_values(DrawingStatus)


def assert_time_entry(data: dict):
    _assert_versioned_common_fields(data, "TimeEntry")
    assert isinstance(data["phase_id"], str)
    assert isinstance(data["staff_member_id"], str)
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert parse_instant(data["end_utc"]) > parse_instant(data["start_utc"]), (
        "TimeEntry.end_utc must be strictly later than start_utc"
    )
    assert isinstance(data["hours"], (int, float)) and data["hours"] > 0
    assert isinstance(data["billable"], bool)
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] >= 0
    assert isinstance(data["billable_cents"], int) and data["billable_cents"] >= 0
    assert data["status"] in _enum_values(TimeEntryStatus)
    if not data["billable"]:
        assert data["billable_cents"] == 0, "a non-billable TimeEntry must carry billable_cents 0"


def assert_expense(data: dict):
    _assert_versioned_common_fields(data, "Expense")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["staff_member_id"], str)
    assert data["category"] in _enum_values(ExpenseCategory)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["reimbursable"], bool)
    assert isinstance(data["markup_bp"], int) and 0 <= data["markup_bp"] <= 5000
    assert isinstance(data["billable_cents"], int) and data["billable_cents"] >= 0
    assert data["status"] in _enum_values(ExpenseStatus)
    if not data["reimbursable"]:
        assert data["billable_cents"] == 0, "a non-reimbursable Expense must carry billable_cents 0"


def assert_rfi(data: dict):
    _assert_versioned_common_fields(data, "RFI")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["rfi_number"], int) and data["rfi_number"] >= 1
    assert isinstance(data["subject"], str) and data["subject"]
    assert data["origin"] in _enum_values(RfiOrigin)
    assert isinstance(data["impacts_fee"], bool)
    assert data["status"] in _enum_values(RfiStatus)
    assert isinstance(data["clarification_rounds"], int) and 0 <= data["clarification_rounds"] <= 2


def assert_submittal(data: dict):
    _assert_versioned_common_fields(data, "Submittal")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["consultant_firm_id"], str)
    assert isinstance(data["spec_section"], str) and data["spec_section"]
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 0
    assert data["status"] in _enum_values(SubmittalStatus)


def assert_change_order(data: dict):
    _assert_versioned_common_fields(data, "ChangeOrder")
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["title"], str) and data["title"]
    assert data["co_type"] in _enum_values(ChangeOrderType)
    assert isinstance(data["fee_delta_cents"], int)
    assert data["status"] in _enum_values(ChangeOrderStatus)
    if data["co_type"] == ChangeOrderType.ADDITIONAL_SERVICE.value:
        assert data["fee_delta_cents"] > 0, "an ADDITIONAL_SERVICE must carry a positive fee_delta_cents"
    else:
        assert data["fee_delta_cents"] < 0, "a SCOPE_REDUCTION must carry a negative fee_delta_cents"


def assert_invoice(data: dict):
    _assert_versioned_common_fields(data, "Invoice")
    assert isinstance(data["contract_id"], str)
    assert data["status"] in _enum_values(InvoiceStatus)
    assert data["payment_status"] in _enum_values(PaymentStatus)
    for field in (
        "fee_billed_cents", "reimbursable_cents", "gross_cents",
        "retainage_bp", "retainage_cents", "net_due_cents", "amount_paid_cents",
    ):
        assert isinstance(data[field], int), f"Invoice.{field} must be an integer"
        assert data[field] >= 0, f"Invoice.{field} must not be negative"
    assert_invoice_money_identity(data)


def assert_invoice_money_identity(data: dict):
    """PRD §3.9 steps 3 and 7: gross = fee + reimbursables; net_due = gross - retainage."""
    assert data["gross_cents"] == data["fee_billed_cents"] + data["reimbursable_cents"], (
        "gross_cents must equal fee_billed_cents + reimbursable_cents"
    )
    assert data["net_due_cents"] == data["gross_cents"] - data["retainage_cents"], (
        "net_due_cents must equal gross_cents - retainage_cents"
    )
    assert data["retainage_bp"] in (0, 500, 1000), (
        f"retainage_bp must be one of the three declared tiers, got {data['retainage_bp']}"
    )


def assert_permit_review(data: dict):
    _assert_versioned_common_fields(data, "PermitReview")
    assert isinstance(data["phase_id"], str)
    assert isinstance(data["jurisdiction_name"], str) and data["jurisdiction_name"]
    assert data["permit_type"] in _enum_values(PermitType)
    assert data["status"] in _enum_values(PermitReviewStatus)
    assert isinstance(data["submission_round"], int) and data["submission_round"] >= 0
    assert isinstance(data["comment_count"], int) and data["comment_count"] >= 0


def assert_field_report(data: dict):
    assert_append_only_common_fields(data, "FieldReport")
    assert isinstance(data["project_id"], str)
    assert isinstance(data["staff_member_id"], str)
    assert isinstance(data["deficiency_count"], int) and data["deficiency_count"] >= 0
    assert isinstance(data["weather"], str)
    assert isinstance(data["observations"], str)
