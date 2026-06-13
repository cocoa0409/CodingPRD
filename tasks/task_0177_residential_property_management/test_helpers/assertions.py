"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the common-field contract (UUID id, ISO 8601
created_at/updated_at, integer version) plus the entity's own fields. Domain
invariant checkers enforce ledger rules that must hold after any operation.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_owner(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["distribution_method"] in ("ACH", "CHECK")
    assert 0 <= data["management_fee_pct"] <= 0.5


def assert_property(data: dict):
    _assert_common(data)
    assert isinstance(data["owner_id"], str) and data["owner_id"]
    assert data["state_code"] in ("CA", "NY", "TX", "IL", "FL")
    assert isinstance(data["trust_balance_cents"], int)
    assert isinstance(data["distributable_cents"], int)
    assert isinstance(data["reserve_floor_cents"], int)
    assert isinstance(data["unit_count"], int)
    assert_property_trust_invariants(data)


def assert_property_trust_invariants(data: dict):
    """Trust ledger invariants (PRD §2.8)."""
    assert data["trust_balance_cents"] >= 0, "trust balance may never go below zero"
    assert data["reserve_floor_cents"] >= 0, "reserve floor may not be negative"
    expected_distributable = max(
        0, data["trust_balance_cents"] - data["reserve_floor_cents"]
    )
    assert data["distributable_cents"] == expected_distributable, (
        "distributable = max(0, trust_balance - reserve_floor)"
    )


def assert_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["property_id"], str) and data["property_id"]
    assert data["market_rent_cents"] > 0
    assert data["occupancy_status"] in ("VACANT_READY", "OCCUPIED", "VACANT_TURN")


def assert_applicant(data: dict):
    _assert_common(data)
    assert isinstance(data["unit_id"], str) and data["unit_id"]
    assert 300 <= data["credit_score"] <= 850
    assert data["annual_income_cents"] >= 0
    assert data["requested_rent_cents"] > 0
    assert data["status"] in (
        "SUBMITTED", "SCREENED", "APPROVED", "DENIED", "LEASED", "WITHDRAWN"
    )
    if data.get("screening_decision") is not None:
        assert data["screening_decision"] in ("PASS", "FAIL")


def assert_lease(data: dict):
    _assert_common(data)
    assert isinstance(data["unit_id"], str) and data["unit_id"]
    assert data["monthly_rent_cents"] > 0
    assert data["end_date"] > data["start_date"]
    assert data["status"] in (
        "DRAFT", "ACTIVE", "RENEWAL_OFFERED", "EXPIRED", "TERMINATED"
    )
    assert data["balance_due_cents"] >= 0


def assert_tenant(data: dict):
    _assert_common(data)
    assert isinstance(data["applicant_id"], str) and data["applicant_id"]
    assert data["status"] in ("CURRENT", "FORMER")


def assert_rent_charge(data: dict):
    _assert_common(data)
    assert isinstance(data["lease_id"], str) and data["lease_id"]
    assert data["charge_type"] in ("RENT", "LATE_FEE")
    assert data["amount_cents"] > 0
    assert data["amount_outstanding_cents"] >= 0
    assert data["status"] in ("OPEN", "PARTIAL", "PAID", "WAIVED")


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["lease_id"], str) and data["lease_id"]
    assert data["amount_cents"] > 0
    assert isinstance(data["applied_breakdown"], list)
    assert data["applied_to_rent_cents"] >= 0
    assert data["unapplied_cents"] >= 0


def assert_security_deposit(data: dict):
    _assert_common(data)
    assert isinstance(data["lease_id"], str) and data["lease_id"]
    assert data["collected_cents"] >= 0
    assert data["status"] in ("HELD", "SETTLED", "FORFEITED")


def assert_work_order(data: dict):
    _assert_common(data)
    assert isinstance(data["unit_id"], str) and data["unit_id"]
    assert data["category"] in (
        "PLUMBING", "ELECTRICAL", "HVAC", "APPLIANCE", "STRUCTURAL", "OTHER"
    )
    assert data["status"] in ("OPEN", "ASSIGNED", "COMPLETED", "CANCELLED")


def assert_eviction(data: dict):
    _assert_common(data)
    assert isinstance(data["lease_id"], str) and data["lease_id"]
    assert data["reason"] in ("NONPAYMENT", "LEASE_VIOLATION", "HOLDOVER")
    assert data["status"] in (
        "NOTICE_SERVED", "CURED", "FILED", "ENFORCED", "DISMISSED"
    )


def assert_owner_statement(data: dict):
    _assert_common(data)
    assert isinstance(data["property_id"], str) and data["property_id"]
    assert data["basis"] in ("CASH", "ACCRUAL")
    assert data["status"] in ("DRAFT", "FINALIZED", "DISTRIBUTED")
    assert data["net_to_owner_cents"] >= 0


def assert_turnover(data: dict):
    _assert_common(data)
    assert isinstance(data["unit_id"], str) and data["unit_id"]
    assert data["status"] in ("OPEN", "IN_PROGRESS", "READY")
