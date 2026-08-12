"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_client(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["ssn_last4"], str) and len(data["ssn_last4"]) == 4
    assert isinstance(data["county_of_residence"], str)
    assert isinstance(data["medicaid_enrolled"], bool)
    assert isinstance(data["medicaid_resource_limit_cents"], int)
    assert data["status"] in ["INTAKE_REVIEW", "ACTIVE", "SUSPENDED", "TERMINATED"]


def assert_entitlement(data: dict):
    _assert_common_fields(data)
    assert data["claim_type"] in ["SSI", "SSDI"]
    assert isinstance(data["monthly_benefit_cents"], int) and data["monthly_benefit_cents"] > 0
    assert isinstance(data["effective_start_date"], str)
    assert data["status"] in ["PENDING_VERIFICATION", "VERIFIED", "TERMINATED"]


def assert_trust_account(data: dict):
    _assert_common_fields(data)
    assert data["account_type"] in ["OPERATING", "RESTRICTED", "DEDICATED"]
    assert isinstance(data["bank_account_ref"], str)
    assert isinstance(data["balance_cents"], int)
    assert data["status"] in ["OPEN", "FROZEN", "CLOSED"]


def assert_ledger_entry(data: dict):
    # Ledger entries are append-only: id + created_at only; no updated_at, no version.
    assert is_valid_uuid(data.get("id", "")), "ledger entry id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger entries must not carry updated_at"
    assert "version" not in data, "ledger entries must not carry version"
    assert data["entry_type"] in [
        "DEPOSIT_POSTED", "DEPOSIT_RETURNED", "DISBURSEMENT_RELEASED", "DISBURSEMENT_RETURNED"
    ]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["balance_after_cents"], int)


def assert_budget_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["period_month"], str)
    assert isinstance(data["source_benefit_cents"], int) and data["source_benefit_cents"] > 0
    assert isinstance(data["lines"], list) and len(data["lines"]) > 0
    assert isinstance(data["allocated_lines"], list) and len(data["allocated_lines"]) > 0
    assert isinstance(data["total_planned_cents"], int)
    assert data["status"] in ["DRAFT", "PROPOSED", "APPROVED", "SUPERSEDED"]


def assert_disbursement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["payee_name"], str)
    assert data["category"] in [
        "HOUSING", "FOOD", "CLOTHING", "PERSONAL", "MEDICAL", "EDUCATION", "SAVINGS"
    ]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["fee_cents"], int)
    assert data["status"] in [
        "REQUESTED", "PENDING_CONSERVATOR", "APPROVED", "RELEASED", "REJECTED", "RETURNED"
    ]


def assert_deposit(data: dict):
    _assert_common_fields(data)
    assert data["source"] in ["SSA_BENEFIT", "PENSION", "REFUND", "OTHER"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["received_date"], str)
    assert data["status"] in ["RECEIVED", "POSTED", "RETURNED"]


def assert_court_order(data: dict):
    _assert_common_fields(data)
    assert data["order_type"] in ["RESTRICTED_WITHDRAWAL", "REPORT_EXTENSION", "BOND_RELIEF"]
    assert isinstance(data["petitioned_date"], str)
    assert isinstance(data["expiry_date"], str)
    assert data["status"] in ["PETITIONED", "GRANTED", "EXECUTED", "EXPIRED"]


def assert_surety_bond(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["coverage_amount_cents"], int) and data["coverage_amount_cents"] > 0
    assert data["status"] in ["PENDING", "ACTIVE", "LAPSED"]
    assert isinstance(data["funds_under_management_cents"], int)
    assert isinstance(data["utilization_bps"], int)


def assert_accounting_report(data: dict):
    _assert_common_fields(data)
    assert data["report_type"] in ["SSA_6233", "COURT_ANNUAL"]
    assert data["basis"] in ["CASH", "ACCRUAL"]
    assert isinstance(data["period_start_date"], str)
    assert isinstance(data["period_end_date"], str)
    assert isinstance(data["due_date"], str)
    assert data["status"] in ["DRAFTING", "SUBMITTED", "ACCEPTED", "REJECTED"]


def assert_spend_down_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["target_month"], str)
    assert isinstance(data["entries"], list)
    assert isinstance(data["provisional_excess_cents"], int)
    assert isinstance(data["auto_created"], bool)
    assert data["status"] in ["DRAFT", "ACTIVE", "MET", "LAPSED"]


def assert_audit_case(data: dict):
    _assert_common_fields(data)
    assert data["authority"] in ["SSA", "STATE_COURT", "BONDING_COMPANY"]
    assert data["scope"] in ["CLIENT_ACCOUNT", "ORG_WIDE"]
    assert data["status"] in ["OPENED", "FINDINGS_ISSUED", "CLOSED_NO_ACTION", "MISUSE_CONFIRMED"]


def assert_conservator(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["court_case_number"], str)
    assert data["authority_scope"] in ["EXCLUSIVE", "SHARED", "ADVISORY"]
    assert data["status"] in ["ACTIVE", "SUSPENDED", "DISCHARGED"]


def assert_budget_allocation_invariant(plan: dict):
    """The per-line amounts always sum to total_planned_cents == source_benefit_cents."""
    total = sum(line["amount_cents"] for line in plan["allocated_lines"])
    assert total == plan["total_planned_cents"], (
        f"allocated_lines sum {total} != total_planned_cents {plan['total_planned_cents']}"
    )
    assert plan["total_planned_cents"] == plan["source_benefit_cents"]


def allocated_amount(plan: dict, category: str) -> int:
    """Return the allocated amount for a category in a plan's allocated_lines."""
    for line in plan["allocated_lines"]:
        if line["category"] == category:
            return line["amount_cents"]
    raise AssertionError(f"category {category} not present in allocated_lines: {plan['allocated_lines']}")
