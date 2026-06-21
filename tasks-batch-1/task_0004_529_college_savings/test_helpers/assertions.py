"""Entity assertions and domain invariant checkers."""
from typing import Any, Dict
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: Dict[str, Any], entity_name: str = "entity") -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be int >= 1"
    )


def assert_donor(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Donor")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["state_code"] in {"CA", "NY", "IL", "TX", "FL", "OH"}
    assert isinstance(data["federal_tax_id_last4"], str) and len(data["federal_tax_id_last4"]) == 4
    assert isinstance(data["email"], str) and "@" in data["email"]


def assert_beneficiary(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Beneficiary")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str) and len(data["date_of_birth"]) >= 10
    assert data["relationship_class"] in {"SELF", "CHILD", "SIBLING", "FIRST_COUSIN", "OTHER"}
    assert isinstance(data["federal_tax_id_last4"], str) and len(data["federal_tax_id_last4"]) == 4


def assert_account(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Account")
    assert data["status"] in {"OPEN", "RESTRICTED", "CLOSED"}
    assert isinstance(data["donor_id"], str) and is_valid_uuid(data["donor_id"])
    assert isinstance(data["beneficiary_id"], str) and is_valid_uuid(data["beneficiary_id"])
    assert isinstance(data["account_balance_cents"], int)
    assert isinstance(data["total_basis_cents"], int)
    assert isinstance(data["total_earnings_cents"], int)
    assert isinstance(data["ytd_qualified_k12_cents"], int)
    assert isinstance(data["tax_year"], int)


def assert_account_invariants(data: Dict[str, Any]) -> None:
    """Account ledger invariants that must hold after any operation."""
    assert data["account_balance_cents"] >= 0, "balance must be non-negative"
    assert data["total_basis_cents"] >= 0, "basis must be non-negative"
    assert data["ytd_qualified_k12_cents"] >= 0, "ytd qualified k12 must be non-negative"
    assert (
        data["total_earnings_cents"] == data["account_balance_cents"] - data["total_basis_cents"]
    ), "earnings must equal balance - basis"


def assert_scheduled_contribution(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "ScheduledContribution")
    assert data["status"] in {"ACTIVE", "PAUSED", "CANCELLED"}
    assert data["cadence"] in {"WEEKLY", "MONTHLY", "QUARTERLY"}
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["posted_runs"], int) and data["posted_runs"] >= 0


def assert_contribution(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Contribution")
    assert data["status"] in {"DRAFT", "POSTED", "REVERSED"}
    assert data["contribution_kind"] in {"LUMP_SUM", "RECURRING"}
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_withdrawal(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Withdrawal")
    assert data["status"] in {"DRAFT", "SUBMITTED", "REJECTED", "APPROVED", "DISBURSED"}
    assert data["expense_class"] in {
        "HIGHER_ED_TUITION",
        "ROOM_BOARD",
        "BOOKS_SUPPLIES",
        "K_12_TUITION",
        "APPRENTICESHIP",
        "NON_QUALIFIED",
    }
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["rejection_count"], int) and data["rejection_count"] >= 0


def assert_withdrawal_split_consistency(data: Dict[str, Any]) -> None:
    """basis_portion_cents + earnings_portion_cents == amount_cents (after APPROVED)."""
    basis = data.get("basis_portion_cents")
    earnings = data.get("earnings_portion_cents")
    if basis is not None and earnings is not None:
        assert basis + earnings == data["amount_cents"], (
            f"basis ({basis}) + earnings ({earnings}) must equal amount ({data['amount_cents']})"
        )


def assert_beneficiary_change(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "BeneficiaryChange")
    assert data["status"] in {"PENDING", "APPROVED", "REJECTED"}


def assert_state_tax_incentive(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "StateTaxIncentive")
    assert data["status"] in {"DRAFT", "CALCULATED", "FINALIZED"}
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["contributions_eligible_cents"], int)
    assert isinstance(data["match_cents"], int)
    assert data["match_cents"] >= 0


def assert_form_1099q(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Form1099Q")
    assert data["status"] in {"DRAFT", "ISSUED", "CORRECTED", "REISSUED"}
    assert data["recipient_kind"] in {"ACCOUNT_OWNER", "BENEFICIARY"}
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["gross_distribution_cents"], int)
    assert isinstance(data["earnings_cents"], int)
    assert isinstance(data["basis_cents"], int)
    assert isinstance(data["penalty_cents"], int)
