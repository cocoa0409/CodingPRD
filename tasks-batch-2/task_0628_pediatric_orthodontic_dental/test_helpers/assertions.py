"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1, got {data.get('version')!r}"


def assert_family_account(data: dict):
    _assert_common(data)
    assert isinstance(data["family_name"], str)
    assert isinstance(data["billing_email"], str)
    assert isinstance(data["discount_tier_pct"], (int, float))
    assert isinstance(data["active_plan_count"], int)


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["is_minor"], bool)
    assert isinstance(data["records_complete"], bool)


def assert_chair(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str)
    assert isinstance(data["turnover_buffer_minutes"], int)
    assert isinstance(data["active"], bool)


def assert_treatment_plan(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "PROPOSED", "ACTIVE", "SUSPENDED",
        "RETENTION", "COMPLETED", "CANCELLED",
    ]
    assert data["modality"] in ["BRACES", "INVISALIGN"]


def assert_contract(data: dict):
    _assert_common(data)
    assert data["billing_status"] in ["CURRENT", "DELINQUENT"]
    assert data["lifecycle_status"] in ["ACTIVE", "CLOSED"]
    assert isinstance(data["financed_amount_cents"], int)
    assert isinstance(data["balance_remaining_cents"], int)


def assert_installment(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "PAID", "MISSED"]
    assert isinstance(data["amount_cents"], int)


def assert_payment(data: dict):
    _assert_common(data)
    assert data["status"] in ["POSTED", "REVERSED"]
    assert data["method"] in ["AUTOPAY", "CARD", "CASH", "CHECK"]


def assert_insurance_policy(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "TERMINATED"]
    assert isinstance(data["remaining_max_cents"], int)
    assert isinstance(data["lifetime_max_cents"], int)


def assert_insurance_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "APPROVED", "PAID", "DENIED", "VOID"]
    assert isinstance(data["benefit_cents"], int)


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "SCHEDULED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW",
    ]
    assert data["visit_type"] in ["BONDING", "ADJUSTMENT", "EMERGENCY", "DEBOND"]


def assert_growth_record(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "FINALIZED", "SUPERSEDED"]
    assert data["record_type"] in ["PANO", "CEPH"]


def assert_retainer(data: dict):
    _assert_common(data)
    assert data["status"] in ["ISSUED", "REPLACED"]
    assert data["retainer_type"] in ["HAWLEY", "CLEAR", "FIXED"]


def assert_lifetime_max_conserved(policy: dict, approved_paid_benefit_sum: int):
    """PRD 2.6: remaining_max_cents == lifetime_max_cents - sum(benefit_cents
    over APPROVED/PAID claims)."""
    assert policy["remaining_max_cents"] == policy["lifetime_max_cents"] - approved_paid_benefit_sum, (
        f"remaining_max {policy['remaining_max_cents']} != "
        f"lifetime_max {policy['lifetime_max_cents']} - benefits {approved_paid_benefit_sum}"
    )


def assert_contract_balance_conserved(contract: dict, posted_payment_sum: int):
    """PRD 2.6: balance_remaining_cents == financed_amount_cents - sum(POSTED
    payment amounts)."""
    assert contract["balance_remaining_cents"] == contract["financed_amount_cents"] - posted_payment_sum, (
        f"balance {contract['balance_remaining_cents']} != "
        f"financed {contract['financed_amount_cents']} - posted {posted_payment_sum}"
    )
