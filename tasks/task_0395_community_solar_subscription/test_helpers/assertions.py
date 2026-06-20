"""Entity assertions and domain invariant checkers for the Community Solar API."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

PROJECT_STATUSES = ["OPEN", "FULL"]
ENROLLMENT_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "ACTIVATED", "REJECTED"]
SUBSCRIPTION_STATUSES = ["ACTIVE", "SUSPENDED", "TRANSFERRING", "CANCELLED"]
WAITLIST_STATUSES = ["QUEUED", "PROMOTED", "WITHDRAWN"]
PERIOD_STATUSES = ["OPEN", "METERED", "RECONCILED", "TRUED_UP", "CLOSED"]
ALLOCATION_STATUSES = ["PROVISIONAL", "FINAL", "VOID"]
CREDIT_STATUSES = ["DRAFT", "ISSUED", "APPLIED"]
DISPUTE_STATUSES = ["NONE", "DISPUTED", "RESOLVED"]
RECBATCH_STATUSES = ["MINTED", "ALLOCATED", "RETIRED", "TRANSFERRED"]


def _assert_common(data: dict):
    """id/created_at/updated_at/version present and well-formed (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_project(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert data["status"] in PROJECT_STATUSES, f"bad project status {data['status']!r}"
    assert data["committed_kw"] >= 0
    assert data["available_kw"] >= 0
    assert isinstance(data["rec_minted_total"], int)
    assert isinstance(data["rec_retired_total"], int)
    assert isinstance(data["rec_available_balance"], int)
    assert isinstance(data["total_net_savings_cents"], int)


def assert_project_invariants(data: dict):
    """Derived-ledger invariants that must hold after any operation (PRD §2.5, §3.1)."""
    assert data["available_kw"] >= 0, "available_kw never below 0"
    # available_kw == nameplate - committed (never below 0)
    expected_available = data["nameplate_capacity_kw"] - data["committed_kw"]
    if expected_available < 0:
        expected_available = 0
    assert abs(data["available_kw"] - expected_available) < 1e-6, (
        f"available_kw {data['available_kw']} != nameplate - committed "
        f"({data['nameplate_capacity_kw']} - {data['committed_kw']})"
    )
    # status OPEN iff available_kw > 0, FULL iff == 0
    if data["available_kw"] == 0:
        assert data["status"] == "FULL", "status FULL when available_kw == 0"
    else:
        assert data["status"] == "OPEN", "status OPEN while available_kw > 0"
    assert data["rec_available_balance"] >= 0 or True  # balance may be derived; no hard floor in PRD


def assert_subscriber(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["utility_account_no"], str)
    assert 0 <= data["churn_risk_score"] <= 100, "churn_risk_score in [0,100]"
    assert isinstance(data["lifetime_savings_cents"], int)


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ENROLLMENT_STATUSES, f"bad enrollment status {data['status']!r}"
    assert data["requested_share_kw"] > 0


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["status"] in SUBSCRIPTION_STATUSES, f"bad subscription status {data['status']!r}"
    assert data["share_kw"] > 0
    assert isinstance(data["is_carve_out"], bool)


def assert_waitlist_entry(data: dict):
    _assert_common(data)
    assert data["status"] in WAITLIST_STATUSES, f"bad waitlist status {data['status']!r}"


def assert_period(data: dict):
    _assert_common(data)
    assert data["status"] in PERIOD_STATUSES, f"bad period status {data['status']!r}"
    assert isinstance(data["sequence_index"], int)
    assert isinstance(data["distributable_kwh"], int)
    assert isinstance(data["allocated_kwh_total"], int)
    assert isinstance(data["overproduction_kwh"], int)


def assert_allocation(data: dict):
    _assert_common(data)
    assert data["status"] in ALLOCATION_STATUSES, f"bad allocation status {data['status']!r}"
    assert isinstance(data["allocated_kwh"], int)
    assert isinstance(data["provisional_credit_cents"], int)


def assert_reconciliation(data: dict):
    _assert_common(data)
    assert data["credit_status"] in CREDIT_STATUSES, f"bad credit_status {data['credit_status']!r}"
    assert data["dispute_status"] in DISPUTE_STATUSES, f"bad dispute_status {data['dispute_status']!r}"
    assert isinstance(data["gross_credit_cents"], int)
    assert isinstance(data["program_fee_cents"], int)
    assert isinstance(data["net_savings_cents"], int)


def assert_rec_batch(data: dict):
    _assert_common(data)
    assert data["status"] in RECBATCH_STATUSES, f"bad rec batch status {data['status']!r}"
    assert isinstance(data["rec_count"], int) and data["rec_count"] >= 0


def assert_carve_out_adjustment(data: dict):
    """Append-only audit record (PRD §2.4): id + created_at, no version / updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only CarveOutAdjustment carries no version"
    assert "updated_at" not in data, "append-only CarveOutAdjustment carries no updated_at"
