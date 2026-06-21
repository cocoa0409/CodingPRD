"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    """id (UUID), created_at/updated_at (ISO 8601), version (int >= 1)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1, got {data['version']}"


def assert_participant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["birth_date"], str) and len(data["birth_date"]) > 0
    assert data["marital_status"] in ("SINGLE", "MARRIED_JOINT", "MARRIED_SEPARATE")
    assert isinstance(data["hdhp_covered"], bool)


def assert_plan_year(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert data["fsa_relief_mode"] in ("NONE", "GRACE_PERIOD", "CARRYOVER")
    assert data["lifecycle"] in ("OPEN", "SETTLED")
    for cap in ("hsa_individual_cap_cents", "hsa_family_cap_cents", "hsa_catchup_cents",
                "health_fsa_cap_cents", "dcfsa_cap_joint_cents", "dcfsa_cap_separate_cents"):
        assert isinstance(data[cap], int)


def assert_account(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("participant_id", "")), "participant_id must be a UUID"
    assert is_valid_uuid(data.get("plan_year_id", "")), "plan_year_id must be a UUID"
    assert data["account_type"] in ("HSA", "HEALTH_FSA", "DCFSA")
    assert data["coverage_tier"] in ("SELF_ONLY", "FAMILY")
    assert data["funding_status"] in ("PENDING", "ACTIVE", "DEPLETED", "CLOSED")
    assert data["compliance_hold"] in ("CLEAR", "HELD")
    for f in ("elected_amount_cents", "contributed_cents", "reimbursed_cents",
              "available_balance_cents", "forfeited_cents", "carried_in_cents",
              "auto_adjudication_threshold_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_contribution(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["source"] in ("PAYROLL", "EMPLOYER", "INDIVIDUAL")
    assert data["status"] in ("POSTED", "REVERSED")


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert data["expense_category"] in (
        "MEDICAL", "DENTAL", "VISION", "PRESCRIPTION", "DEPENDENT_CARE", "OTC")
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] > 0
    assert isinstance(data["substantiated"], bool)
    assert isinstance(data["reimbursable_amount_cents"], int)
    assert data["status"] in (
        "SUBMITTED", "PENDING_SUBSTANTIATION", "APPROVED", "DENIED", "REIMBURSED", "VOIDED")


def assert_batch(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("participant_id", "")), "participant_id must be a UUID"
    assert isinstance(data["claim_ids"], list)
    assert isinstance(data["total_reimbursed_cents"], int)
    assert data["status"] in ("DRAFT", "SETTLED", "PARTIAL")


def assert_ledger_entry(data: dict):
    """LedgerEntry is append-only: only id + created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only LedgerEntry must not carry updated_at"
    assert "version" not in data, "append-only LedgerEntry must not carry version"
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert data["entry_type"] in (
        "CONTRIBUTION", "CONTRIBUTION_REVERSAL", "REIMBURSEMENT", "REIMBURSEMENT_REVERSAL",
        "FORFEITURE", "CARRYOVER_OUT", "CARRYOVER_IN")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0, \
        "ledger amount_cents is always a positive integer magnitude"


def assert_fsa_election_pool_conserved(account: dict, expected_pool: int):
    """For a HEALTH_FSA/DCFSA: available_balance_cents + reimbursed_cents must equal
    elected_amount_cents + carried_in_cents (the election pool), with zero drift."""
    pool = account["available_balance_cents"] + account["reimbursed_cents"]
    assert pool == expected_pool, (
        f"election pool drift: available {account['available_balance_cents']} + "
        f"reimbursed {account['reimbursed_cents']} == {pool}, expected {expected_pool}")
