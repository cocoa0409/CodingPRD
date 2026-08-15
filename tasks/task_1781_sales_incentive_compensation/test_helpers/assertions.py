"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the envelope-independent resource shape: the
common system fields (id/created_at/updated_at/version) plus the fields the
PRD names for that resource. assert_payroll_export instead enforces the
append-only exception: id + created_at present, updated_at/version absent.
"""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    AcceptanceStatus,
    AdjustmentSource,
    AdjustmentStatus,
    AssignmentStatus,
    AttainmentMode,
    CreditStatus,
    CreditType,
    DisputeReason,
    DisputeStatus,
    PlanStatus,
    StatementStatus,
    TransactionStatus,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def assert_comp_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["current_period_index"], int)
    assert data["current_period_index"] >= 1
    assert isinstance(data["accrued_balance_cents"], int)


def assert_comp_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["effective_start_date"], str)
    assert isinstance(data["effective_end_date"], str)
    tiers = data["curve_tiers"]
    assert isinstance(tiers, list) and len(tiers) > 0
    for tier in tiers:
        assert isinstance(tier["attainment_floor_bps"], int)
        assert isinstance(tier["rate_bps"], int)
    assert data["attainment_mode"] in _enum_values(AttainmentMode)
    assert isinstance(data["rollup_rate_bps"], int)
    assert data["rollup_rate_bps"] >= 0
    assert data.get("payout_cap_cents") is None or data["payout_cap_cents"] > 0
    assert isinstance(data["document_version"], int)
    assert isinstance(data["created_by_user_id"], str)
    assert data["status"] in _enum_values(PlanStatus)


def assert_rep(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["employee_ref"], str)
    assert data.get("manager_id") is None or isinstance(data["manager_id"], str)


def assert_plan_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["rep_id"], str)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["quota_cents"], int) and data["quota_cents"] > 0
    assert isinstance(data["draw_amount_cents_per_period"], int)
    assert data["draw_amount_cents_per_period"] >= 0
    assert isinstance(data["draw_recoverable"], bool)
    assert isinstance(data["guarantee_amount_cents_per_period"], int)
    assert data["guarantee_amount_cents_per_period"] >= 0
    assert isinstance(data["effective_start_date"], str)
    assert (data.get("effective_end_date") is None
            or isinstance(data["effective_end_date"], str))
    assert data["status"] in _enum_values(AssignmentStatus)
    assert data["acceptance_status"] in _enum_values(AcceptanceStatus)
    assert (data.get("accepted_document_version") is None
            or isinstance(data["accepted_document_version"], int))
    for field in ("draw_outstanding_cents", "draw_forgiven_cents",
                  "current_period_earned_cents", "current_attainment_bps",
                  "provisional_period_payout_cents", "lifetime_earned_cents",
                  "lifetime_paid_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_sales_transaction(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["external_ref"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["transaction_date"], str)
    splits = data["splits"]
    assert isinstance(splits, list) and len(splits) > 0
    for split in splits:
        assert isinstance(split["rep_id"], str)
        assert isinstance(split["split_bps"], int) and split["split_bps"] > 0
    assert isinstance(data["booked_period_index"], int)
    assert data["status"] in _enum_values(TransactionStatus)


def assert_credit_entry(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["transaction_id"], str)
    assert isinstance(data["assignment_id"], str)
    assert isinstance(data["rep_id"], str)
    assert (data.get("parent_credit_id") is None
            or isinstance(data["parent_credit_id"], str))
    assert data["credit_type"] in _enum_values(CreditType)
    assert isinstance(data["credit_amount_cents"], int)
    assert (data.get("posted_period_index") is None
            or isinstance(data["posted_period_index"], int))
    assert data["status"] in _enum_values(CreditStatus)


def assert_adjustment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["assignment_id"], str)
    assert (data.get("dispute_id") is None
            or isinstance(data["dispute_id"], str))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] != 0
    assert data["source"] in _enum_values(AdjustmentSource)
    assert isinstance(data["reason"], str)
    assert isinstance(data["period_index"], int)
    assert isinstance(data["created_by_user_id"], str)
    assert data["status"] in _enum_values(AdjustmentStatus)


def assert_dispute(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["assignment_id"], str)
    assert (data.get("credit_entry_id") is None
            or isinstance(data["credit_entry_id"], str))
    assert isinstance(data["period_index"], int)
    assert data["reason"] in _enum_values(DisputeReason)
    assert isinstance(data["requested_amount_cents"], int)
    assert data["requested_amount_cents"] > 0
    assert (data.get("approved_amount_cents") is None
            or isinstance(data["approved_amount_cents"], int))
    assert data["status"] in _enum_values(DisputeStatus)


def assert_payout_statement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["assignment_id"], str)
    assert isinstance(data["period_index"], int)
    for field in ("earned_credits_cents", "adjustments_cents",
                  "earned_total_cents", "attainment_bps", "gross_payout_cents",
                  "draw_paid_cents", "draw_recovered_cents",
                  "guarantee_trueup_cents", "deficit_cents",
                  "net_payable_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["payout_cap_applied"], bool)
    assert data["status"] in _enum_values(StatementStatus)


def assert_payroll_export(data: dict):
    """Append-only record: id + created_at only; NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, "PayrollExport must not carry updated_at"
    assert "version" not in data, "PayrollExport must not carry version"
    assert isinstance(data["program_id"], str)
    assert isinstance(data["period_index"], int)
    assert isinstance(data["statement_ids"], list)
    assert isinstance(data["statement_count"], int)
    assert data["statement_count"] == len(data["statement_ids"])
    assert isinstance(data["total_cents"], int)


def assert_draw_ledger_invariant(assignment: dict, statements: list):
    """Draw debt conservation: outstanding == paid - recovered - forgiven.

    `statements` must be every closed statement of the assignment.
    """
    paid = sum(s["draw_paid_cents"] for s in statements)
    recovered = sum(s["draw_recovered_cents"] for s in statements)
    forgiven = assignment["draw_forgiven_cents"]
    outstanding = assignment["draw_outstanding_cents"]
    assert outstanding == paid - recovered - forgiven, (
        f"draw ledger drift: outstanding {outstanding} != paid {paid} "
        f"- recovered {recovered} - forgiven {forgiven}"
    )
