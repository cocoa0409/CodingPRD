"""Entity assertions and domain invariant checkers (PRD 2.5, 3.2)."""
from typing import Any, Dict

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: Dict[str, Any], label: str = "resource"):
    """id / created_at / updated_at / version, per PRD 2.5."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_allocation_fields(data: Dict[str, Any], label: str = "allocation"):
    """Append-only ledger entry: id and created_at only; no updated_at, no version (PRD 2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, f"{label} must expose no updated_at field"
    assert "version" not in data, f"{label} must expose no version field"


def assert_property(data: Dict[str, Any]):
    assert_common_fields(data, "Property")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["posting_priority_policy"] in ("FEES_FIRST", "RENT_FIRST")
    for field in (
        "late_fee_cap_cents",
        "nsf_fee_cap_cents",
        "monthly_waiver_cap_cents",
        "collections_threshold_cents",
        "plan_setup_fee_cents",
        "plan_setup_fee_threshold_cents",
    ):
        assert isinstance(data[field], int), f"Property.{field} must be an integer"
    assert isinstance(data["min_partial_payment_percent"], int)
    assert 1 <= data["min_partial_payment_percent"] <= 100
    assert isinstance(data["notice_cure_period_days"], int)
    assert isinstance(data["plan_cooling_off_days"], int)


def assert_tenant(data: Dict[str, Any]):
    assert_common_fields(data, "Tenant")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data.get("phone", ""), str)


def assert_lease(data: Dict[str, Any]):
    assert_common_fields(data, "Lease")
    assert is_valid_uuid(data.get("property_id", "")), "Lease.property_id must be a UUID"
    assert is_valid_uuid(data.get("primary_tenant_id", "")), "Lease.primary_tenant_id must be a UUID"
    assert isinstance(data["unit_label"], str) and data["unit_label"]
    assert isinstance(data["monthly_rent_cents"], int)
    assert isinstance(data["due_day"], int) and 1 <= data["due_day"] <= 28
    assert isinstance(data["grace_period_days"], int)
    assert data["late_fee_type"] in ("FLAT", "PERCENT_PLUS_DAILY")
    assert data["status"] in ("DRAFT", "ACTIVE", "ENDED")
    assert isinstance(data["term_start_date"], str)
    assert isinstance(data["term_end_date"], str)


def assert_charge(data: Dict[str, Any]):
    assert_common_fields(data, "LedgerCharge")
    assert is_valid_uuid(data.get("lease_id", "")), "LedgerCharge.lease_id must be a UUID"
    assert data["kind"] in ("RENT", "LATE_FEE", "NSF_FEE", "PLAN_SETUP_FEE", "DAMAGE_FEE")
    assert data["source"] in ("MANUAL", "SWEEP", "PLAN", "RETURN")
    assert data["status"] in ("OPEN", "PARTIALLY_PAID", "PAID", "WAIVED", "VOID")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["waived_cents"], int)
    assert isinstance(data["outstanding_cents"], int)
    assert isinstance(data["period_start_date"], str)
    assert isinstance(data["period_end_date"], str)
    assert isinstance(data["due_date"], str)
    assert isinstance(data.get("created_by_user_id"), str)


def assert_payment(data: Dict[str, Any]):
    assert_common_fields(data, "Payment")
    assert is_valid_uuid(data.get("lease_id", "")), "Payment.lease_id must be a UUID"
    assert is_valid_uuid(data.get("tenant_id", "")), "Payment.tenant_id must be a UUID"
    assert data["channel"] in ("ACH", "CARD", "CHECK", "MONEY_ORDER", "CASH")
    assert data["status"] in ("PENDING", "POSTED", "RETURNED")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["received_date"], str)
    assert isinstance(data["return_count"], int)


def assert_allocation(data: Dict[str, Any]):
    assert_allocation_fields(data, "PaymentAllocation")
    assert is_valid_uuid(data.get("payment_id", "")), "PaymentAllocation.payment_id must be a UUID"
    assert is_valid_uuid(data.get("charge_id", "")), "PaymentAllocation.charge_id must be a UUID"
    assert data["direction"] in ("APPLY", "REVERSE")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["allocation_order"], int) and data["allocation_order"] >= 1


def assert_notice(data: Dict[str, Any]):
    assert_common_fields(data, "DelinquencyNotice")
    assert is_valid_uuid(data.get("lease_id", "")), "DelinquencyNotice.lease_id must be a UUID"
    assert isinstance(data["charge_ids"], list) and len(data["charge_ids"]) >= 1
    assert data["status"] in ("DRAFT", "ISSUED", "SERVED", "CURED", "EXPIRED", "CANCELLED")
    assert isinstance(data["amount_demanded_cents"], int)
    assert isinstance(data["period_start_date"], str)
    assert isinstance(data["period_end_date"], str)


def assert_plan(data: Dict[str, Any]):
    assert_common_fields(data, "PaymentPlan")
    assert is_valid_uuid(data.get("lease_id", "")), "PaymentPlan.lease_id must be a UUID"
    assert isinstance(data["charge_ids"], list) and len(data["charge_ids"]) >= 1
    assert data["status"] in ("DRAFT", "ACTIVE", "CURED", "DEFAULTED", "CANCELLED")
    assert isinstance(data["setup_fee_cents"], int)
    assert isinstance(data["scheduled_total_cents"], int)
    assert isinstance(data["installment_count"], int) and 2 <= data["installment_count"] <= 12
    assert isinstance(data["installments"], list)
    for inst in data["installments"]:
        assert isinstance(inst["sequence_number"], int) and inst["sequence_number"] >= 1
        assert isinstance(inst["due_date"], str)
        assert isinstance(inst["amount_cents"], int)
        assert inst["status"] in ("PENDING", "PAID", "MISSED")


def assert_dispute(data: Dict[str, Any]):
    assert_common_fields(data, "Dispute")
    assert is_valid_uuid(data.get("lease_id", "")), "Dispute.lease_id must be a UUID"
    assert is_valid_uuid(data.get("charge_id", "")), "Dispute.charge_id must be a UUID"
    assert is_valid_uuid(data.get("tenant_id", "")), "Dispute.tenant_id must be a UUID"
    assert data["status"] in ("OPEN", "RESOLVED_UPHELD", "RESOLVED_ADJUSTED", "REOPENED")
    assert isinstance(data["reopen_count"], int)


def assert_referral(data: Dict[str, Any]):
    assert_common_fields(data, "CollectionsReferral")
    assert is_valid_uuid(data.get("lease_id", "")), "CollectionsReferral.lease_id must be a UUID"
    assert data["status"] in ("PENDING", "REFERRED", "SETTLED", "RECALLED")
    assert isinstance(data["referred_balance_cents"], int)


def assert_ledger_identity(ledger: Dict[str, Any]):
    """The ledger identity: total_charged == total_waived + total_outstanding + total_applied_net."""
    charged = ledger["total_charged_cents"]
    waived = ledger["total_waived_cents"]
    outstanding = ledger["total_outstanding_cents"]
    applied = ledger["total_applied_net_cents"]
    assert charged == waived + outstanding + applied, (
        f"Ledger identity violated: total_charged_cents {charged} != "
        f"{waived} + {outstanding} + {applied}"
    )
