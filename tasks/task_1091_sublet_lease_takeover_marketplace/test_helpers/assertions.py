"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_landlord(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0


def assert_leaseholder(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0


def assert_applicant(data: dict):
    _assert_common(data)
    assert isinstance(data["annual_income_cents"], int) and data["annual_income_cents"] >= 0
    assert isinstance(data["monthly_debt_cents"], int) and data["monthly_debt_cents"] >= 0
    assert 300 <= data["credit_score"] <= 850
    assert isinstance(data["active_application_count"], int) and data["active_application_count"] >= 0


def assert_lease(data: dict):
    _assert_common(data)
    assert data["status"] in ["UNVERIFIED", "PENDING_REVIEW", "VERIFIED", "REJECTED"]
    assert data["monthly_rent_cents"] > 0
    assert data["security_deposit_cents"] >= 0
    assert isinstance(data["active_occupancy_count"], int) and data["active_occupancy_count"] >= 0


def assert_listing(data: dict):
    _assert_common(data)
    assert data["listing_type"] in ["SUBLET", "TAKEOVER"]
    assert data["screening_policy"] in ["STANDARD", "STRICT"]
    assert data["status"] in [
        "DRAFT", "PENDING_APPROVAL", "OPEN", "MATCHED", "CLOSED", "DECLINED", "WITHDRAWN"
    ]
    assert data["asking_rent_cents"] > 0


def assert_application(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "SUBMITTED", "SCREENING", "INFO_REQUESTED", "SCREENED", "MATCHED", "DECLINED", "WITHDRAWN"
    ]
    assert data["screening_result"] in ["PENDING", "PASS", "FAIL"]


def assert_screening_report(data: dict):
    _assert_common(data)
    assert data["screening_policy"] in ["STANDARD", "STRICT"]
    assert data["qualification_result"] in ["PASS", "FAIL"]
    assert isinstance(data["affordability_ratio"], (int, float))
    assert isinstance(data["income_multiple"], (int, float))


def assert_agreement(data: dict):
    _assert_common(data)
    assert data["agreement_type"] in ["SUBLET", "TAKEOVER"]
    assert data["status"] in [
        "DRAFT", "PENDING_SIGNATURES", "EXECUTED", "ACTIVE", "COMPLETED", "VOID", "TERMINATED"
    ]
    assert isinstance(data["required_signer_roles"], list)
    assert isinstance(data["is_fully_signed"], bool)


def assert_signature(data: dict):
    # common_fields: false — only id + created_at are system-managed.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["signer_role"] in ["LANDLORD", "LEASEHOLDER", "APPLICANT"]


def assert_settlement(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "PENDING", "FUNDED", "HANDED_OFF", "RELEASED", "REFUNDED", "FORFEITED"
    ]
    assert data["deposit_amount_cents"] >= 0
    assert data["deposit_held_cents"] >= 0


def assert_handoff_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_dispute(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "FILED", "UNDER_REVIEW", "RESOLVED_LEASEHOLDER", "RESOLVED_APPLICANT",
        "RESOLVED_SPLIT", "DISMISSED",
    ]


def assert_fee(data: dict):
    _assert_common(data)
    assert data["fee_type"] in ["PLATFORM", "SCREENING", "CANCELLATION", "LATE"]
    assert data["status"] in ["PENDING", "CHARGED", "WAIVED", "REFUNDED"]
    assert data["amount_cents"] >= 0
