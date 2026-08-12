"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_employer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["funding_model"] in ("PREFUNDED", "PAY_AS_YOU_GO")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_benefit_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["employer_id"])
    assert isinstance(data["benefit_year"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")


def assert_member(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["employer_id"])
    assert is_valid_uuid(data["plan_id"])
    assert data["tier_code"] in ("INDIVIDUAL", "COUPLE", "FAMILY")
    assert data["eligibility_status"] in ("PENDING", "ELIGIBLE", "SUSPENDED", "TERMINATED")


def assert_dependent(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert data["relationship"] in ("SPOUSE", "CHILD", "DOMESTIC_PARTNER")
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_provider(data: dict):
    _assert_common_fields(data)
    assert data["modality"] in ("GYM", "STUDIO", "APP", "POOL")
    assert data["network_tier"] in ("IN_NETWORK", "PREFERRED", "OUT_OF_NETWORK")
    assert data["status"] in ("PENDING_ONBOARD", "ACTIVE", "SUSPENDED", "TERMINATED")


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["plan_id"])
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "CLOSED")
    assert isinstance(data["used_cents"], int) and data["used_cents"] >= 0
    assert isinstance(data["reserved_cents"], int) and data["reserved_cents"] >= 0
    assert isinstance(data["annual_allowance_cents"], int)


def assert_visit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["provider_id"])
    assert data["verification_method"] in ("GEO_FENCE", "POS_SWIPE", "MANUAL_REVIEW")
    assert data["status"] in ("RECORDED", "VERIFIED", "REJECTED", "VOIDED")
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0
    assert isinstance(data["fraud_score"], int) and 0 <= data["fraud_score"] <= 100


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert data["claim_type"] in ("REIMBURSEMENT", "DIRECT_PAY")
    assert data["review_status"] in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO", "APPROVED", "REJECTED")
    assert data["payment_status"] in ("UNPAID", "PAID", "REVERSED", "CLAWED_BACK")
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] > 0
    assert isinstance(data["resubmission_count"], int) and data["resubmission_count"] >= 0


def assert_funding_account(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["employer_id"])
    assert data["status"] in ("FUNDED", "DEPLETED", "SUSPENDED")
    for f in ("funded_cents", "available_cents", "reserved_cents", "disbursed_cents"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_funding_entry(data: dict):
    # Ledger entries carry only id + created_at (no updated_at / version).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["entry_type"] in ("DEPOSIT", "HOLD", "RELEASE", "DEBIT", "CLAWBACK_CREDIT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["running_available_cents"], int)


def assert_fraud_flag(data: dict):
    _assert_common_fields(data)
    assert data["signal"] in (
        "VELOCITY", "OVERLAP_PATTERN", "DUPLICATE_RECEIPT", "GEOFENCE_MISMATCH", "PROVIDER_PATTERN",
    )
    assert data["status"] in ("OPEN", "CONFIRMED", "CLEARED")
    assert isinstance(data["severity"], int) and 1 <= data["severity"] <= 10


def assert_statement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert data["status"] in ("OPEN", "FINALIZED", "DELIVERED")
    assert isinstance(data["provisional_total_cents"], int)
    assert isinstance(data["claim_count"], int) and data["claim_count"] >= 0


def assert_allowance_invariants(allowance: dict):
    """Enrollment ledger invariant: used + reserved + remaining == annual allowance."""
    total = allowance["used_cents"] + allowance["reserved_cents"] + allowance["remaining_cents"]
    assert total == allowance["annual_allowance_cents"], (
        f"used {allowance['used_cents']} + reserved {allowance['reserved_cents']} "
        f"+ remaining {allowance['remaining_cents']} != annual {allowance['annual_allowance_cents']}"
    )
    assert allowance["used_cents"] >= 0
    assert allowance["reserved_cents"] >= 0


def assert_funding_conservation(account: dict, clawback_credits: int = 0):
    """Funding ledger invariant: funded + clawback credits == available + reserved + disbursed."""
    lhs = account["funded_cents"] + clawback_credits
    rhs = account["available_cents"] + account["reserved_cents"] + account["disbursed_cents"]
    assert lhs == rhs, f"funded+credits {lhs} != available+reserved+disbursed {rhs}"
