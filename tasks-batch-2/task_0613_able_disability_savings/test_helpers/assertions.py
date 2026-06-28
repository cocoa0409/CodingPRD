"""Entity assertions and domain invariant checkers for the ABLE program API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at its initial value and increments"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str)
    assert isinstance(data["annual_contribution_cap_cents"], int)
    assert isinstance(data["able_to_work_fpl_cents"], int)
    assert isinstance(data["program_fee_bps"], int)


def assert_investment_option(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert data["risk_tier"] in ("CONSERVATIVE", "MODERATE", "AGGRESSIVE", "CASH")
    assert isinstance(data["is_open"], bool)


def assert_beneficiary(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["full_name"], str)
    assert data["eligibility_status"] in ("UNCERTIFIED", "CERTIFIED", "DENIED", "EXPIRED")
    assert isinstance(data["is_deceased"], bool)
    assert isinstance(data["other_countable_resources_cents"], int)


def assert_certification(data: dict):
    _assert_common(data)
    assert isinstance(data["beneficiary_id"], str)
    assert data["basis"] in ("SSI_SSDI_ENTITLEMENT", "DISABILITY_DIAGNOSIS")
    assert data["status"] in ("PENDING", "CERTIFIED", "DENIED", "EXPIRED")
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["expires_on"], str)


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["beneficiary_id"], str)
    assert isinstance(data["investment_option_id"], str)
    assert data["status"] in ("OPEN", "SUSPENDED", "FROZEN_DEATH", "CLOSED")
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["basis_cents"], int)
    assert isinstance(data["earnings_cents"], int)
    assert isinstance(data["regular_contrib_ytd_cents"], int)
    assert isinstance(data["atw_contrib_ytd_cents"], int)
    assert isinstance(data["investment_changes_ytd"], int)
    assert data["ssi_posture"] in ("SSI_OK", "SSI_SUSPENDED")


def assert_account_ledger_invariant(data: dict):
    """balance = basis + earnings - distributed; the contribution ledger conserves."""
    assert data["balance_cents"] == data["basis_cents"] + data["earnings_cents"], (
        f"balance ({data['balance_cents']}) must equal basis ({data['basis_cents']}) "
        f"+ earnings ({data['earnings_cents']})"
    )


def assert_representative(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert data["relationship"] in ("PARENT", "GUARDIAN", "POA_AGENT", "SPOUSE")
    assert data["status"] in ("ACTIVE", "REVOKED")


def assert_contribution(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert data["contribution_type"] in ("REGULAR", "ABLE_TO_WORK", "ROLLOVER_529")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("POSTED", "REVERSED")


def assert_distribution(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["category"] in (
        "HOUSING", "EDUCATION", "HEALTH", "TRANSPORTATION", "BASIC_LIVING", "LEGAL", "OTHER",
    )
    assert data["status"] in (
        "REQUESTED", "APPROVED", "DISBURSED", "REJECTED", "SUBSTANTIATED", "CLAWED_BACK",
    )


def assert_qde_record(data: dict):
    _assert_common(data)
    assert isinstance(data["distribution_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["receipt_reference"], str)


def assert_medicaid_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["claimed_amount_cents"], int)
    assert isinstance(data["allowed_payback_cents"], int)
    assert isinstance(data["residual_to_estate_cents"], int)
    assert data["status"] in ("FILED", "SETTLED")
