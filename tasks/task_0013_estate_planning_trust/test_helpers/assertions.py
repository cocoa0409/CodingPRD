"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict, label: str) -> None:
    """Common-resource-property checks (id, created_at, updated_at, version).

    Per PRD §2.4 — every entity carries the full set.
    """
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be int >= 1"
    )


def assert_decedent(data: dict) -> None:
    _assert_common(data, "Decedent")
    assert isinstance(data["full_legal_name"], str) and data["full_legal_name"]
    assert is_iso8601_timestamp(data["date_of_birth"]), (
        "Decedent.date_of_birth must be ISO 8601"
    )
    assert data["domicile_state_code"] in {"CA", "NY", "TX", "FL", "IL"}, (
        f"Decedent.domicile_state_code must be CA/NY/TX/FL/IL, got "
        f"{data['domicile_state_code']!r}"
    )
    assert isinstance(data["ssn_last4"], str) and len(data["ssn_last4"]) == 4


def assert_estate(data: dict) -> None:
    _assert_common(data, "Estate")
    assert is_valid_uuid(data.get("decedent_id", "")), (
        "Estate.decedent_id must be UUID"
    )
    assert data["status"] in {
        "DRAFT", "ALIVE", "DECEASED", "PROBATE_PENDING", "PROBATE_OPEN",
        "ADMINISTRATION", "CLOSED", "CONTESTED",
    }, f"Estate.status {data['status']!r} invalid"
    assert isinstance(data["gross_estate_value_cents"], int) and (
        data["gross_estate_value_cents"] >= 0
    )
    assert isinstance(data["net_taxable_estate_cents"], int) and (
        data["net_taxable_estate_cents"] >= 0
    )


def assert_asset(data: dict) -> None:
    _assert_common(data, "Asset")
    assert is_valid_uuid(data["estate_id"])
    assert data["category"] in {
        "REAL_ESTATE", "BROKERAGE", "BANK_ACCOUNT", "RETIREMENT_IRA",
        "LIFE_INSURANCE", "PERSONAL_PROPERTY", "BUSINESS_INTEREST",
    }
    assert isinstance(data["appraised_value_cents"], int) and (
        data["appraised_value_cents"] >= 0
    )
    assert data["status"] in {"DRAFT", "INCLUDED", "EXCLUDED", "LIQUIDATED"}


def assert_beneficiary_designation(data: dict) -> None:
    _assert_common(data, "BeneficiaryDesignation")
    assert is_valid_uuid(data["estate_id"])
    assert isinstance(data["beneficiary_full_name"], str)
    assert data["relationship"] in {
        "SPOUSE", "CHILD", "GRANDCHILD", "PARENT", "SIBLING", "CHARITY", "OTHER",
    }
    assert isinstance(data["share_basis_points"], int) and (
        0 < data["share_basis_points"] <= 10000
    )
    assert data["status"] in {"DRAFT", "ACTIVE", "REVOKED"}


def assert_executor(data: dict) -> None:
    _assert_common(data, "Executor")
    assert is_valid_uuid(data["estate_id"])
    assert data["role_type"] in {"EXECUTOR", "TRUSTEE"}
    assert data["status"] in {
        "NOMINATED", "ACCEPTED", "DECLINED", "COURT_CONFIRMED",
        "DISCHARGED", "REMOVED",
    }


def assert_power_of_attorney(data: dict) -> None:
    _assert_common(data, "PowerOfAttorney")
    assert is_valid_uuid(data["decedent_id"])
    assert data["scope"] in {
        "FINANCIAL", "HEALTHCARE", "DURABLE_FINANCIAL", "DURABLE_HEALTHCARE",
    }
    assert data["status"] in {"DRAFT", "ACTIVE", "REVOKED", "TERMINATED"}


def assert_directive(data: dict) -> None:
    _assert_common(data, "EndOfLifeDirective")
    assert is_valid_uuid(data["decedent_id"])
    assert data["directive_type"] in {
        "LIVING_WILL", "DNR", "HEALTHCARE_POA", "HIPAA_AUTHORIZATION",
    }
    assert data["status"] in {
        "DRAFT", "WITNESSED", "NOTARIZED", "ACTIVE", "REVOKED",
    }


def assert_guardianship(data: dict) -> None:
    _assert_common(data, "Guardianship")
    assert is_valid_uuid(data["estate_id"])
    assert data["status"] in {
        "PROPOSED", "COURT_REVIEW", "COURT_CONFIRMED", "COURT_DENIED", "DISSOLVED",
    }


def assert_creditor_claim(data: dict) -> None:
    _assert_common(data, "CreditorClaim")
    assert is_valid_uuid(data["estate_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["claim_class"] in {
        "SECURED", "ADMIN", "FUNERAL", "TAX", "UNSECURED",
    }
    assert data["status"] in {"FILED", "ALLOWED", "DISALLOWED", "PAID"}
    assert isinstance(data["paid_amount_cents"], int) and (
        data["paid_amount_cents"] >= 0
    )


def assert_probate_order(data: dict) -> None:
    _assert_common(data, "ProbateOrder")
    assert is_valid_uuid(data["estate_id"])
    assert data["order_type"] in {
        "OPEN_PROBATE", "CONFIRM_EXECUTOR", "APPROVE_INVENTORY",
        "SETTLE_CREDITORS", "FINAL_DISTRIBUTION", "CLOSE_ESTATE",
    }
    assert data["status"] in {"DRAFT", "ENTERED", "SUPERSEDED"}
