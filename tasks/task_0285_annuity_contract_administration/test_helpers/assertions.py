"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response structure against the PRD
contract using the framework's generic format checkers.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_product(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["contract_type"] in ("FIXED", "VARIABLE", "INDEXED")
    assert data["death_benefit_type"] in (
        "RETURN_OF_PREMIUM", "ACCOUNT_VALUE", "HIGHEST_ANNIVERSARY"
    )
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["version"], int)


def assert_contract(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["owner_name"], str) and len(data["owner_name"]) > 0
    assert data["status"] in (
        "PENDING", "ACTIVE", "ANNUITIZED", "SURRENDERED", "DEATH_CLAIM", "TERMINATED"
    )
    assert isinstance(data["accumulation_value_cents"], int)
    assert data["accumulation_value_cents"] >= 0
    assert isinstance(data["version"], int)


def assert_premium(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("SUBMITTED", "CLEARED", "REJECTED")
    assert isinstance(data["gross_premium_cents"], int)
    assert isinstance(data["version"], int)


def assert_sub_account_allocation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ("ACTIVE", "LIQUIDATED")
    assert isinstance(data["allocation_bps"], int)
    assert isinstance(data["version"], int)


def assert_index_segment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ("OPEN", "CREDITED")
    assert isinstance(data["cap_bps"], int)
    assert isinstance(data["version"], int)


def assert_withdrawal(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ("REQUESTED", "SETTLED", "REJECTED")
    assert isinstance(data["requested_amount_cents"], int)
    assert isinstance(data["version"], int)


def assert_beneficiary(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ("ACTIVE", "REVOKED")
    assert isinstance(data["share_bps"], int)
    assert isinstance(data["version"], int)


def assert_annuitization(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ("ELECTED", "ACTIVE_PAYOUT", "DECLINED")
    assert data["payout_option"] in (
        "LIFE_ONLY", "PERIOD_CERTAIN", "LIFE_WITH_PERIOD_CERTAIN", "JOINT_LIFE"
    )
    assert isinstance(data["version"], int)


def assert_death_claim(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ("FILED", "VERIFYING", "VALUED", "FUNDED", "DENIED")
    assert isinstance(data["version"], int)


def assert_exchange1035(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["direction"] in ("INBOUND", "OUTBOUND")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "SETTLED", "REJECTED"
    )
    assert isinstance(data["revision_count"], int)
    assert isinstance(data["version"], int)


def assert_crediting_event(data: dict):
    """CreditingEvent is append-only: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "CreditingEvent is append-only and must not carry version"
    assert "updated_at" not in data, "CreditingEvent is append-only and must not carry updated_at"
    assert isinstance(data["credit_cents"], int)
    assert data["credit_cents"] >= 0, "credit_cents is never negative"
