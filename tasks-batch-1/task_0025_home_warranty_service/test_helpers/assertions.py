"""Entity assertion helpers — one per primary entity, plus domain invariants.

Each assertion verifies what PRD §2.4 / §3.x explicitly guarantees about the
entity's response shape; tolerant of additional fields the implementer may add.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


_CONTRACT_PACKAGE_STATUSES = {"ACTIVE", "RETIRED"}
_CONTRACT_STATUSES = {
    "PENDING_PAYMENT", "ACTIVE", "EXPIRING_SOON",
    "EXPIRED", "CANCELLED", "RENEWED",
}
_CLAIM_STATUSES = {"SUBMITTED", "ASSESSED", "DISPATCHED", "RESOLVED", "REJECTED"}
_DISPATCH_STATUSES = {"SCHEDULED", "IN_PROGRESS", "COMPLETED", "RETURN_NEEDED"}
_ITEM_CATEGORIES = {
    "HVAC", "WATER_HEATER", "REFRIGERATOR", "DISHWASHER",
    "WASHER", "DRYER", "OVEN",
}
_REJECTION_REASONS = {
    "PRE_EXISTING_EXCLUDED", "OUT_OF_COVERAGE", "NOT_COVERED_CATEGORY",
}


def _assert_common_fields(data: dict, entity_name: str = "entity") -> None:
    """PRD §2.4: every mutable primary entity carries id (UUID), created_at,
    updated_at, version (int >= 1)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be int >= 1, got {data.get('version')!r}"
    )


def _assert_append_only_fields(data: dict, entity_name: str = "entity") -> None:
    """PRD §2.4: RenewalReminder carries id + created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )


# ─── ContractPackage ────────────────────────────────────────────


def assert_contract_package(data: dict) -> None:
    """Validate ContractPackage response shape (PRD §3.1)."""
    _assert_common_fields(data, "ContractPackage")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["annual_premium_cents"], int) and data["annual_premium_cents"] >= 0
    assert isinstance(data["service_fee_cents"], int) and data["service_fee_cents"] >= 0
    assert isinstance(data["copay_cap_cents"], int) and data["copay_cap_cents"] >= 0
    assert isinstance(data["copay_share_pct"], (int, float))
    assert 0 <= data["copay_share_pct"] <= 1
    assert isinstance(data["return_visit_window_days"], int) and data["return_visit_window_days"] >= 0
    assert isinstance(data["max_covered_items"], int) and data["max_covered_items"] >= 1
    assert data["status"] in _CONTRACT_PACKAGE_STATUSES


# ─── Customer ───────────────────────────────────────────────────


def assert_customer(data: dict) -> None:
    """Validate Customer response shape (PRD §3.1)."""
    _assert_common_fields(data, "Customer")
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["home_address"], str) and data["home_address"]


# ─── Contract ───────────────────────────────────────────────────


def assert_contract(data: dict) -> None:
    """Validate Contract response shape (PRD §3.2)."""
    _assert_common_fields(data, "Contract")
    assert is_valid_uuid(data["customer_id"]), "Contract.customer_id must be a UUID"
    assert is_valid_uuid(data["package_id"]), "Contract.package_id must be a UUID"
    assert data["status"] in _CONTRACT_STATUSES, (
        f"Contract.status must be a known status, got {data['status']!r}"
    )
    # claims_in_period_count / total_paid_out_cents / annual_premium_due_cents are
    # always present on every read (PRD §2.9, §3.2, §3.4).
    assert isinstance(data["claims_in_period_count"], int) and data["claims_in_period_count"] >= 0
    assert isinstance(data["total_paid_out_cents"], int) and data["total_paid_out_cents"] >= 0
    assert isinstance(data["annual_premium_due_cents"], int) and data["annual_premium_due_cents"] >= 0


def assert_active_contract(data: dict) -> None:
    """An ACTIVE contract has stamped coverage_start/end_utc (PRD §3.2)."""
    assert_contract(data)
    assert data["status"] in {"ACTIVE", "EXPIRING_SOON"}
    assert is_iso8601_timestamp(data["coverage_start_utc"]), (
        f"Contract.coverage_start_utc must be ISO 8601 after activation"
    )
    assert is_iso8601_timestamp(data["coverage_end_utc"]), (
        f"Contract.coverage_end_utc must be ISO 8601 after activation"
    )


# ─── CoveredItem ────────────────────────────────────────────────


def assert_covered_item(data: dict) -> None:
    """Validate CoveredItem response shape (PRD §3.3)."""
    _assert_common_fields(data, "CoveredItem")
    assert is_valid_uuid(data["contract_id"]), "CoveredItem.contract_id must be a UUID"
    assert data["category"] in _ITEM_CATEGORIES
    assert isinstance(data["brand"], str) and data["brand"]
    assert isinstance(data["model"], str) and data["model"]
    assert isinstance(data["install_year"], int)
    assert isinstance(data["pre_existing_flag"], bool)


# ─── ClaimTicket ────────────────────────────────────────────────


def assert_claim(data: dict) -> None:
    """Validate ClaimTicket response shape (PRD §3.4)."""
    _assert_common_fields(data, "ClaimTicket")
    assert is_valid_uuid(data["contract_id"]), "ClaimTicket.contract_id must be a UUID"
    assert is_valid_uuid(data["covered_item_id"]), "ClaimTicket.covered_item_id must be a UUID"
    assert isinstance(data["issue_summary"], str)
    assert data["status"] in _CLAIM_STATUSES, (
        f"ClaimTicket.status must be a known status, got {data['status']!r}"
    )
    assert isinstance(data["is_return_visit"], bool)
    assert isinstance(data["repair_cost_cents"], int) and data["repair_cost_cents"] >= 0
    assert isinstance(data["provisional_copay_cents"], int) and data["provisional_copay_cents"] >= 0
    assert isinstance(data["final_copay_cents"], int) and data["final_copay_cents"] >= 0
    assert isinstance(data["service_fee_charged_cents"], int) and data["service_fee_charged_cents"] >= 0
    rr = data.get("rejection_reason")
    assert rr is None or rr in _REJECTION_REASONS


# ─── Dispatch ───────────────────────────────────────────────────


def assert_dispatch(data: dict) -> None:
    """Validate Dispatch response shape (PRD §3.5)."""
    _assert_common_fields(data, "Dispatch")
    assert is_valid_uuid(data["claim_id"]), "Dispatch.claim_id must be a UUID"
    assert isinstance(data["technician_id"], str) and data["technician_id"]
    assert isinstance(data["scheduled_utc"], str) and data["scheduled_utc"]
    assert data["status"] in _DISPATCH_STATUSES


# ─── RenewalReminder ────────────────────────────────────────────


def assert_renewal_reminder(data: dict) -> None:
    """RenewalReminder is append-only — id + created_at only (PRD §2.4, §3.8)."""
    _assert_append_only_fields(data, "RenewalReminder")
    assert is_valid_uuid(data["contract_id"]), "RenewalReminder.contract_id must be a UUID"
    assert isinstance(data["sent_utc"], str) and data["sent_utc"]
    assert isinstance(data["days_to_expiry"], int) and data["days_to_expiry"] >= 0
