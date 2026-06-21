"""Entity assertions and domain invariant checkers (PRD §2.4, §2.7, §3).

Per PRD §2.4: Product, CoverageTier, Registration, ExtendedWarranty,
ProofOfPurchase, Claim carry id/created_at/updated_at/version; Owner,
WarrantyTransfer, LedgerEntry carry ONLY id and created_at (no updated_at,
no version) — their assertions never demand those fields.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict) -> None:
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


def assert_minimal_audit_fields(data: dict) -> None:
    """id + created_at only; updated_at/version MUST be absent (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_product(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["model_number"], str) and data["model_number"]
    assert data["category"] in ("ELECTRONICS", "APPLIANCE", "POWER_TOOL", "FURNITURE")
    assert isinstance(data["msrp_cents"], int) and data["msrp_cents"] >= 1
    assert isinstance(data["base_warranty_months"], int) and data["base_warranty_months"] >= 0
    assert isinstance(data["serviceable_lifespan_months"], int) and data["serviceable_lifespan_months"] >= 1
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_owner(data: dict) -> None:
    assert_minimal_audit_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_coverage_tier(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert data["tier_name"] in ("BASE", "SILVER", "GOLD", "PLATINUM")
    assert isinstance(data["extension_months"], int) and data["extension_months"] >= 0
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["coverage_cap_cents"], int) and data["coverage_cap_cents"] >= 1
    assert data["depreciation_method"] in ("STRAIGHT_LINE", "DECLINING_BALANCE")
    assert isinstance(data["refund_eligible"], bool)
    assert data["premium_refund_method"] in ("PRO_RATA", "SHORT_RATE")
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_registration(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["owner_user_id"], str) and data["owner_user_id"]
    assert is_iso8601_timestamp(data["purchase_date"])
    assert isinstance(data["purchase_price_cents"], int) and data["purchase_price_cents"] >= 1
    assert data["proof_status"] in ("UNVERIFIED", "VALIDATED", "REJECTED")
    assert is_iso8601_timestamp(data["warranty_end_date"])
    assert isinstance(data["remaining_coverage_cents"], int)
    assert data["status"] in ("REGISTERED", "ACTIVE", "TRANSFER_PENDING", "EXPIRED", "VOIDED")


def assert_extended_warranty(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["registration_id"])
    assert is_valid_uuid(data["coverage_tier_id"])
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0
    assert is_iso8601_timestamp(data["effective_date"])
    assert isinstance(data["premium_refund_cents"], int) and data["premium_refund_cents"] >= 0
    assert data["status"] in ("ACTIVE", "CANCELLED")


def assert_proof_of_purchase(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["registration_id"])
    assert data["document_type"] in ("RECEIPT", "INVOICE", "BANK_STATEMENT")
    assert is_iso8601_timestamp(data["stated_purchase_date"])
    assert isinstance(data["stated_amount_cents"], int) and data["stated_amount_cents"] >= 0
    assert data["status"] in ("SUBMITTED", "VALIDATED", "REJECTED")
    assert data.get("rejection_reason") in (
        None, "DATE_MISMATCH", "AMOUNT_MISMATCH", "EXPIRED_WINDOW"
    )


def assert_claim(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["registration_id"])
    assert data["defect_category"] in ("MANUFACTURING", "WEAR_AND_TEAR", "ACCIDENTAL", "COSMETIC")
    assert is_iso8601_timestamp(data["reported_date"])
    assert data.get("resolution_type") in (None, "REPAIR", "REPLACE", "REFUND")
    assert isinstance(data["assessed_value_cents"], int) and data["assessed_value_cents"] >= 0
    assert data["status"] in ("INTAKE", "RMA_ISSUED", "ADJUDICATED", "FULFILLED", "DENIED", "CLOSED")


def assert_warranty_transfer(data: dict) -> None:
    assert_minimal_audit_fields(data)
    assert is_valid_uuid(data["registration_id"])
    assert isinstance(data["from_owner_user_id"], str) and data["from_owner_user_id"]
    assert isinstance(data["to_owner_user_id"], str) and data["to_owner_user_id"]
    assert isinstance(data["transfer_fee_cents"], int) and data["transfer_fee_cents"] >= 0
    assert data["status"] in ("COMPLETED", "REVERSED")


def assert_ledger_entry(data: dict) -> None:
    assert_minimal_audit_fields(data)
    assert is_valid_uuid(data["registration_id"])
    assert data["entry_type"] in ("DEBIT", "CREDIT")
    assert data["reason"] in (
        "REPAIR_COST", "REPLACE_COST", "REFUND_PAYOUT", "REVERSAL", "TRANSFER_FEE"
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def assert_coverage_conserved(registration: dict, debits: int, credits: int, cap: int) -> None:
    """PRD §2.7 conserved quantity: cap == remaining + debits - credits, with the
    reconciled remaining clamped at a floor of zero."""
    expected = max(0, cap - debits + credits)
    assert registration["remaining_coverage_cents"] == expected, (
        f"remaining_coverage_cents {registration['remaining_coverage_cents']} != "
        f"clamp(cap {cap} - debits {debits} + credits {credits}) = {expected}"
    )
    assert registration["remaining_coverage_cents"] >= 0, "remaining coverage must never be negative"
