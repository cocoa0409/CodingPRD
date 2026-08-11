"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

CERTIFICATE_NUMBER_RE = re.compile(r"^CERT-[0-9A-F]{8}$")


def _assert_common_fields(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity_label}.version must be an integer"


def _assert_append_only_fields(data: dict, entity_label: str):
    # CustodyEvent and LedgerEntry carry only id and created_at (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"


def assert_business_account(data: dict):
    _assert_common_fields(data, "BusinessAccount")
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["contact_email"], str) and len(data["contact_email"]) > 0
    assert data["tier"] in ("STANDARD", "VOLUME", "ENTERPRISE")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["lifetime_diverted_kg"], (int, float))


def assert_recycler(data: dict):
    _assert_common_fields(data, "Recycler")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["certification_standard"] in ("R2", "E_STEWARDS")
    assert is_iso8601_timestamp(data["certification_expires_at"])
    assert isinstance(data["accepted_categories"], list) and len(data["accepted_categories"]) > 0
    for cat in data["accepted_categories"]:
        assert cat in ("LAPTOP", "DESKTOP", "SERVER", "PHONE", "TABLET", "MONITOR", "BATTERY", "OTHER")
    assert isinstance(data["daily_intake_capacity_kg"], (int, float))
    assert isinstance(data["violation_count"], int) and data["violation_count"] >= 0
    assert isinstance(data["total_processed_kg"], (int, float))
    assert isinstance(data["risk_score"], (int, float))


def assert_compliance_policy(data: dict):
    _assert_common_fields(data, "CompliancePolicy")
    assert data["standard"] in ("R2", "E_STEWARDS")
    assert isinstance(data["sanitization_methods_allowed"], list) and len(data["sanitization_methods_allowed"]) > 0
    for method in data["sanitization_methods_allowed"]:
        assert method in ("CRYPTO_ERASE", "NIST_CLEAR", "NIST_PURGE", "PHYSICAL_DESTROY")
    assert isinstance(data["export_allowed"], bool)
    assert isinstance(data["resale_requires_verified_sanitization"], bool)
    assert isinstance(data["is_active"], bool)
    for w in ("weight_cert_freshness", "weight_volume", "weight_violations"):
        assert isinstance(data[w], (int, float)), f"{w} must be numeric"


def assert_manifest(data: dict):
    _assert_common_fields(data, "Manifest")
    assert is_valid_uuid(data.get("account_id", "")), "Manifest.account_id must be a UUID"
    assert data["mode"] in ("PICKUP", "DROPOFF")
    assert isinstance(data["declared_item_count"], int) and data["declared_item_count"] >= 1
    assert isinstance(data["received_item_count"], int) and data["received_item_count"] >= 0
    assert isinstance(data["discrepancy_flag"], bool)
    assert data["status"] in ("DRAFT", "SCHEDULED", "RECEIVED", "RECONCILED", "CLOSED", "CANCELLED")


def assert_item(data: dict):
    _assert_common_fields(data, "Item")
    assert is_valid_uuid(data.get("manifest_id", "")), "Item.manifest_id must be a UUID"
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert data["category"] in ("LAPTOP", "DESKTOP", "SERVER", "PHONE", "TABLET", "MONITOR", "BATTERY", "OTHER")
    assert isinstance(data["weight_kg"], (int, float)) and data["weight_kg"] > 0
    assert isinstance(data["data_bearing"], bool)
    assert isinstance(data["hazmat_flag"], bool)
    assert data["declared_grade"] in ("A", "B", "C", "D")
    assert data["disposition"] in ("NONE", "RESALE", "REFURB", "RECYCLE")
    assert data["processing_status"] in (
        "INTAKE", "FOR_RESALE", "FOR_REFURB", "FOR_RECYCLE", "LISTED",
        "SOLD", "BATCHED", "DOWNSTREAM", "COMPLETE",
    )
    assert data["data_status"] in ("NOT_REQUIRED", "PENDING", "SANITIZED", "VERIFIED")
    assert "recycle_batch_id" in data, "Item.recycle_batch_id must be present (null outside BATCHED/DOWNSTREAM)"
    if data["recycle_batch_id"] is not None:
        assert is_valid_uuid(data["recycle_batch_id"]), "Item.recycle_batch_id must be a UUID when set"
    assert isinstance(data["provisional_value_cents"], int)
    assert isinstance(data["final_value_cents"], int)


def assert_data_sanitization(data: dict):
    _assert_common_fields(data, "DataSanitization")
    assert is_valid_uuid(data.get("item_id", "")), "DataSanitization.item_id must be a UUID"
    assert data["method"] in ("CRYPTO_ERASE", "NIST_CLEAR", "NIST_PURGE", "PHYSICAL_DESTROY")
    assert data["outcome"] in ("PASS", "FAIL")
    assert isinstance(data["logged_by_id"], str) and len(data["logged_by_id"]) > 0
    assert data["status"] in ("LOGGED", "VERIFIED", "REJECTED")


def assert_resale_listing(data: dict):
    _assert_common_fields(data, "ResaleListing")
    assert is_valid_uuid(data.get("item_id", "")), "ResaleListing.item_id must be a UUID"
    assert isinstance(data["asking_price_cents"], int)
    assert isinstance(data["floor_price_cents"], int) and data["floor_price_cents"] >= 0
    assert data["channel"] in ("B2B_AUCTION", "RETAIL")
    assert data["status"] in ("ACTIVE", "SOLD", "RETURNED", "WITHDRAWN")


def assert_recycle_batch(data: dict):
    _assert_common_fields(data, "RecycleBatch")
    assert is_valid_uuid(data.get("recycler_id", "")), "RecycleBatch.recycler_id must be a UUID"
    assert is_iso8601_timestamp(data["scheduled_delivery_date"])
    assert isinstance(data["is_export"], bool)
    assert data["status"] in ("STAGING", "IN_TRANSIT", "DELIVERED", "PROCESSED")
    assert isinstance(data["gross_weight_kg"], (int, float))
    assert isinstance(data["item_count"], int) and data["item_count"] >= 0


def assert_custody_event(data: dict):
    _assert_append_only_fields(data, "CustodyEvent")
    assert "updated_at" not in data, "CustodyEvent must not carry updated_at (append-only)"
    assert "version" not in data, "CustodyEvent must not carry version (append-only)"
    assert data["subject_type"] in ("MANIFEST", "ITEM", "BATCH")
    assert isinstance(data["subject_id"], str) and len(data["subject_id"]) > 0
    assert data["event_type"] in (
        "RECEIVED_FACILITY", "TRANSFERRED", "SHIPPED_DOWNSTREAM",
        "DELIVERED_DOWNSTREAM", "PROCESSED",
    )
    assert isinstance(data["actor_id"], str) and len(data["actor_id"]) > 0


def assert_certificate(data: dict):
    _assert_common_fields(data, "Certificate")
    assert data["cert_type"] in ("DATA_DESTRUCTION", "RECYCLING")
    assert CERTIFICATE_NUMBER_RE.match(data["certificate_number"]), (
        f"certificate_number must match CERT-<8 uppercase hex>, got {data['certificate_number']!r}"
    )
    assert isinstance(data["issued_by_id"], str) and len(data["issued_by_id"]) > 0
    assert data["status"] in ("ISSUED", "VOIDED")


def assert_settlement(data: dict):
    _assert_common_fields(data, "Settlement")
    assert is_valid_uuid(data.get("manifest_id", "")), "Settlement.manifest_id must be a UUID"
    assert data["kind"] in ("QUOTE", "FINAL")
    assert data["status"] in ("QUOTE_OPEN", "SUPERSEDED", "FINALIZED", "PAID", "VOIDED")
    for f in ("gross_buyback_cents", "total_fees_cents", "volume_rebate_cents", "net_amount_cents"):
        assert isinstance(data[f], int), f"Settlement.{f} must be integer cents"


def assert_ledger_entry(data: dict):
    _assert_append_only_fields(data, "LedgerEntry")
    assert "updated_at" not in data, "LedgerEntry must not carry updated_at (append-only)"
    assert "version" not in data, "LedgerEntry must not carry version (append-only)"
    assert is_valid_uuid(data.get("account_id", "")), "LedgerEntry.account_id must be a UUID"
    assert is_valid_uuid(data.get("settlement_id", "")), "LedgerEntry.settlement_id must be a UUID"
    assert data["entry_type"] in (
        "BUYBACK_CREDIT", "FEE_DEBIT", "BONUS_CREDIT", "PAYOUT_DEBIT", "REVERSAL",
    )
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["balance_after_cents"], int)
