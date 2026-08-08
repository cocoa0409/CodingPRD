"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_common_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_bid(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("FORMING", "ACTIVE", "RENEWAL_PENDING", "EXPIRED")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["min_assessment_cents"], int)
    assert isinstance(data["max_assessment_cents"], int)


def assert_parcel(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("ACTIVE", "WITHDRAWN")
    assert isinstance(data["exempt"], bool)
    assert isinstance(data["weighted_base"], (int, float))


def assert_fiscal_year(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("UPCOMING", "ACTIVE")
    assert data["budget_status"] in ("NONE", "DRAFT", "PROPOSED", "ADOPTED")
    assert data["collection_status"] in ("OPEN", "FULLY_COLLECTED")
    assert isinstance(data["total_certified_levy_cents"], int)
    assert isinstance(data["collected_to_date_cents"], int)


def assert_budget(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("DRAFT", "PROPOSED", "ADOPTED")
    assert isinstance(data["required_levy_cents"], int)
    assert isinstance(data["allocated_total_cents"], int)


def assert_work_plan_line(data: dict):
    _assert_common_versioned(data)
    assert data["category"] in ("CLEAN", "SAFE", "MARKETING", "ADMIN", "CONTINGENCY")
    assert isinstance(data["allocated_amount_cents"], int)
    assert isinstance(data["spent_amount_cents"], int)


def assert_assessment(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("ESTIMATED", "CERTIFIED", "ADJUSTED", "CANCELLED")
    assert isinstance(data["weighted_base"], (int, float))


def assert_collection_account(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("BILLED", "DELINQUENT", "PAID", "CREDIT", "WRITTEN_OFF")
    assert isinstance(data["billed_amount_cents"], int)
    assert isinstance(data["balance_due_cents"], int)


def assert_payment(data: dict):
    """Payment is an append-only ledger event: id + created_at ONLY (no version/updated_at)."""
    _assert_common(data)
    assert "version" not in data, "Payment must not carry version (append-only)"
    assert "updated_at" not in data, "Payment must not carry updated_at (append-only)"
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data.get("posted_at", "")), "posted_at must be ISO 8601"


def assert_dispute(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED",
        "RESOLVED_ADJUSTED", "RESOLVED_DENIED", "WITHDRAWN",
    )


def assert_renewal_petition(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in (
        "CIRCULATING", "SUBMITTED", "VERIFIED", "FAILED", "APPROVED", "REJECTED",
    )


def assert_petition_signature(data: dict):
    """PetitionSignature is append-only: id + created_at ONLY."""
    _assert_common(data)
    assert "version" not in data, "PetitionSignature must not carry version (append-only)"
    assert "updated_at" not in data, "PetitionSignature must not carry updated_at (append-only)"
    assert isinstance(data["support"], bool)


def assert_ambassador(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_ambassador_shift(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("SCHEDULED", "CANCELLED")


def assert_service_request(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in (
        "OPEN", "ASSIGNED", "IN_PROGRESS", "RESOLVED", "CLOSED", "CANCELLED",
    )
