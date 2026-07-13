"""Entity assertions and domain invariant checkers for the LIHEAP API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_funding_pool(data: dict):
    _assert_common(data)
    assert data["program_component"] in ("HEATING", "COOLING", "CRISIS")
    assert data["status"] in ("OPEN", "LOW", "DEPLETED", "CLOSED")
    assert isinstance(data["total_allocation_cents"], int)
    assert isinstance(data["reserved_cents"], int)
    assert isinstance(data["disbursed_cents"], int)
    assert isinstance(data["available_cents"], int)
    assert_pool_conservation(data)


def assert_pool_conservation(data: dict):
    """PRD §2.7: allocation == available + reserved + disbursed, after every operation."""
    assert (
        data["total_allocation_cents"]
        == data["available_cents"] + data["reserved_cents"] + data["disbursed_cents"]
    ), (
        "pool conservation violated: "
        f"{data['total_allocation_cents']} != {data['available_cents']} + "
        f"{data['reserved_cents']} + {data['disbursed_cents']}"
    )


def assert_household(data: dict):
    _assert_common(data)
    assert isinstance(data["primary_applicant_name"], str) and data["primary_applicant_name"]
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert data["heating_source"] in ("ELECTRICITY", "NATURAL_GAS", "FUEL_OIL", "PROPANE")


def assert_application(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED")
    assert data["program_component"] in ("HEATING", "COOLING")


def assert_income_document(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "VERIFIED", "REJECTED")
    assert data["doc_type"] in ("PAYSTUB", "TAX_RETURN", "BENEFIT_LETTER", "SELF_ATTESTATION")


def assert_vendor(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ENROLLED")
    assert data["vendor_type"] in ("ELECTRIC", "GAS", "OIL", "PROPANE", "WATER")


def assert_utility_account(data: dict):
    _assert_common(data)
    assert isinstance(data["current_balance_cents"], int)
    assert isinstance(data["arrearage_cents"], int)
    assert isinstance(data["lifetime_credited_cents"], int)
    assert isinstance(data["original_obligation_cents"], int)
    assert_account_conservation(data)


def assert_account_conservation(data: dict):
    """PRD §2.8: arrearage + current_balance + lifetime_credited == original_obligation."""
    assert (
        data["arrearage_cents"] + data["current_balance_cents"] + data["lifetime_credited_cents"]
        == data["original_obligation_cents"]
    ), (
        "account ledger conservation violated: "
        f"{data['arrearage_cents']} + {data['current_balance_cents']} + "
        f"{data['lifetime_credited_cents']} != {data['original_obligation_cents']}"
    )


def assert_pledge(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLEDGED", "PAID", "CANCELLED", "EXPIRED")
    assert data["pledge_type"] in ("HEATING", "COOLING", "CRISIS", "RECONNECTION", "ARREARAGE")


def assert_crisis_benefit(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "RESOLVED", "BREACHED")
    assert data["crisis_type"] in ("NO_HEAT", "DISCONNECTION_NOTICE", "OUT_OF_FUEL")


def assert_payment(data: dict):
    _assert_common(data)
    assert data["status"] in ("INITIATED", "REMITTED", "RETURNED")


def assert_bill_credit(data: dict):
    _assert_common(data)
    assert data["status"] in ("APPLIED", "REVERSED")


def assert_weatherization_referral(data: dict):
    _assert_common(data)
    assert data["status"] in ("REFERRED", "SCHEDULED")
    assert data["priority"] in ("HIGH", "MEDIUM", "LOW")
