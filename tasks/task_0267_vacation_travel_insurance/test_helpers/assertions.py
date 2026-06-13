"""Entity assertions and domain invariant checkers for the Vacation Travel Insurance API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version for full entities (§2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["tier"] in ("BASIC", "STANDARD", "PREMIER")
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["base_rate_bps"], int) and data["base_rate_bps"] >= 1
    assert 1 <= data["cancellation_limit_pct"] <= 100
    assert 1 <= data["cfar_reimbursement_pct"] <= 100


def assert_traveler(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["date_of_birth"], str)


def assert_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["owner_traveler_id"], str)
    assert isinstance(data["trip_cost_cents"], int) and data["trip_cost_cents"] >= 1
    assert data["payment_status"] in ("PENDING", "PAID", "REFUNDED")
    assert data["coverage_status"] in ("QUOTED", "ACTIVE", "EXPIRED", "CANCELLED", "EXHAUSTED")
    assert isinstance(data["base_premium_cents"], int)
    assert isinstance(data["premium_cents"], int)


def assert_insured_traveler(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["traveler_id"], str)
    assert isinstance(data["age_at_departure"], int) and data["age_at_departure"] >= 0
    assert isinstance(data["covered_trip_cost_cents"], int) and data["covered_trip_cost_cents"] >= 0
    assert data["status"] in ("COVERED", "REMOVED")


def assert_named_storm(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["basin"] in ("ATLANTIC", "EAST_PACIFIC", "WEST_PACIFIC", "INDIAN")
    assert data["status"] in ("ACTIVE", "DISSIPATED")


def assert_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["insured_traveler_id"], str)
    assert data["peril"] in ("CANCELLATION", "MEDICAL", "DELAY", "BAGGAGE")
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "DENIED", "PAID"
    )


def assert_claim_expense(data: dict):
    _assert_common(data)
    assert isinstance(data["claim_id"], str)
    assert data["category"] in ("PREPAID_TRIP", "MEDICAL_BILL", "BAGGAGE_ITEM", "DELAY_EXPENSE")
    assert isinstance(data["documented_amount_cents"], int) and data["documented_amount_cents"] >= 0


def assert_claim_document(data: dict):
    """ClaimDocument is append-only: id + created_at only, NO updated_at / version (§2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["claim_id"], str)
    assert data["doc_type"] in ("RECEIPT", "MEDICAL_REPORT", "CARRIER_DELAY_LETTER", "POLICE_REPORT", "OTHER")


def assert_payout(data: dict):
    _assert_common(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ("PENDING", "DISBURSED", "REVERSED")


def assert_refund(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str)
    assert data["refund_type"] in ("FREE_LOOK", "SHORT_RATE")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ("PENDING", "COMPLETED", "VOIDED")


def assert_policy_aggregate_invariants(data: dict):
    """Ledger conservation invariants on a Policy (§2.7).

    Only checks fields that exist once the ledger is seeded (i.e. after issuance,
    when aggregate_limit_cents is pinned)."""
    if data.get("aggregate_limit_cents") is not None and data.get("amount_reimbursed_cents") is not None:
        assert data["remaining_aggregate_cents"] == \
            data["aggregate_limit_cents"] - data["amount_reimbursed_cents"], \
            "remaining_aggregate_cents must equal aggregate_limit_cents - amount_reimbursed_cents"
        assert data["remaining_aggregate_cents"] >= 0, "remaining_aggregate_cents must not be negative"
        assert data["amount_reimbursed_cents"] >= 0, "amount_reimbursed_cents must not be negative"
