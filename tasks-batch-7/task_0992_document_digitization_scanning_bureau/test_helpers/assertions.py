"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _assert_common_fields(data: dict, entity_label: str, with_version: bool = True):
    assert isinstance(data, dict), f"{entity_label} must be a dict"
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_label}.updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{entity_label}.version must be an int >= 1"
    else:
        # Append-only event rows MUST NOT carry version or updated_at.
        assert "version" not in data, f"{entity_label} is append-only and must not expose version"
        assert "updated_at" not in data, f"{entity_label} is append-only and must not expose updated_at"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_client(data: dict):
    _assert_common_fields(data, "Client")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["hipaa_covered"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_service_agreement(data: dict):
    _assert_common_fields(data, "ServiceAgreement")
    assert is_valid_uuid(data["client_id"])
    assert data["price_tier"] in ("STANDARD", "VOLUME")
    assert isinstance(data["rush_multiplier"], (int, float)) and data["rush_multiplier"] > 0
    assert isinstance(data["storage_free_days"], int) and data["storage_free_days"] >= 0
    assert isinstance(data["storage_daily_rate_cents"], int) and data["storage_daily_rate_cents"] >= 0
    assert isinstance(data["retention_days"], int) and data["retention_days"] >= 0
    assert isinstance(data["max_boxes_per_batch"], int) and data["max_boxes_per_batch"] >= 1


def assert_batch(data: dict):
    _assert_common_fields(data, "Batch")
    assert is_valid_uuid(data["client_id"])
    assert data["priority"] in ("STANDARD", "RUSH")
    assert data["status"] in (
        "INTAKE", "PREPPING", "SCANNING", "QA", "INDEXING",
        "DELIVERED", "DISPOSITION_PENDING", "CLOSED",
    )
    assert isinstance(data["scanned_pages"], int) and data["scanned_pages"] >= 0
    assert isinstance(data["billable_scanned_pages"], int) and data["billable_scanned_pages"] >= 0
    assert isinstance(data["rework_cycle_count"], int) and data["rework_cycle_count"] >= 0
    assert data["delivery_status"] in ("PENDING", "PARTIAL", "COMPLETE")
    assert data.get("delivered_at") is None or is_iso8601_timestamp(data["delivered_at"])
    assert data.get("disposition_at") is None or is_iso8601_timestamp(data["disposition_at"])
    assert isinstance(data["projected_storage_fee_cents"], int) and data["projected_storage_fee_cents"] >= 0


def assert_box(data: dict):
    _assert_common_fields(data, "Box")
    assert is_valid_uuid(data["batch_id"])
    assert isinstance(data["box_label"], str) and len(data["box_label"]) > 0
    assert isinstance(data["intake_weight_grams"], int) and data["intake_weight_grams"] >= 1
    assert data["status"] in (
        "RECEIVED", "STORED", "IN_PREP", "IN_SCAN", "SCAN_COMPLETE",
        "AWAITING_DISPOSITION", "IN_DESTRUCTION", "DESTROYED", "RETURNED",
    )
    assert isinstance(data["return_requested"], bool)
    assert isinstance(data["custody_flagged"], bool)


def assert_document(data: dict):
    _assert_common_fields(data, "Document")
    assert is_valid_uuid(data["box_id"])
    assert is_valid_uuid(data["batch_id"])
    assert data["doc_type"] in ("MEDICAL_RECORD", "INVOICE", "CONTRACT", "CORRESPONDENCE", "OTHER")
    assert isinstance(data["pages"], int) and data["pages"] >= 1
    assert isinstance(data["contains_phi"], bool)
    assert isinstance(data["ocr_confidence"], int) and 0 <= data["ocr_confidence"] <= 100
    assert data["status"] in ("REGISTERED", "SCANNED", "QA_FAILED", "INDEXED", "DELIVERED", "REJECTED")
    assert data.get("delivered_at") is None or is_iso8601_timestamp(data["delivered_at"])


def assert_scan_session(data: dict):
    _assert_common_fields(data, "ScanSession")
    assert is_valid_uuid(data["batch_id"])
    assert is_valid_uuid(data["scanner_id"])
    assert isinstance(data["operator_id"], str) and len(data["operator_id"]) > 0
    assert data["status"] in ("OPEN", "COMMITTED", "VOIDED")
    assert isinstance(data["page_count"], int) and data["page_count"] >= 0
    assert is_iso8601_timestamp(data["started_at"])
    assert data.get("ended_at") is None or is_iso8601_timestamp(data["ended_at"])


def assert_page_log(data: dict):
    """Append-only event: only id + created_at common fields."""
    _assert_common_fields(data, "PageLog", with_version=False)
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["batch_id"])
    assert is_valid_uuid(data["document_id"])
    assert isinstance(data["pages"], int) and data["pages"] >= 1


def assert_index_record(data: dict):
    _assert_common_fields(data, "IndexRecord")
    assert is_valid_uuid(data["document_id"])
    assert is_valid_uuid(data["batch_id"])
    assert isinstance(data["metadata_json"], dict)
    assert isinstance(data["ocr_text_ref"], str)


def assert_access_grant(data: dict):
    _assert_common_fields(data, "AccessGrant")
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["batch_id"])
    assert data["scope"] in ("METADATA_ONLY", "FULL_IMAGE")
    assert is_iso8601_timestamp(data["expires_at"])
    assert isinstance(data["vault_only"], bool)
    assert data["status"] in ("ACTIVE", "REVOKED", "EXPIRED")


def assert_custody_event(data: dict):
    """Append-only event: only id + created_at common fields."""
    _assert_common_fields(data, "CustodyEvent", with_version=False)
    assert is_valid_uuid(data["box_id"])
    assert isinstance(data["from_stage"], str)
    assert isinstance(data["to_stage"], str)
    assert isinstance(data["actor_user_id"], str)
    assert isinstance(data["actor_role"], str)


def assert_destruction_certificate(data: dict):
    _assert_common_fields(data, "DestructionCertificate")
    assert is_valid_uuid(data["box_id"])
    assert is_valid_uuid(data["batch_id"])
    assert isinstance(data["witness_user_id"], str) and len(data["witness_user_id"]) > 0
    assert data["method"] in ("SHRED", "INCINERATE", "PULP")
    assert isinstance(data["certificate_code"], str) and len(data["certificate_code"]) > 0
    assert is_iso8601_timestamp(data["destroyed_at"])


def assert_scanner_unit(data: dict):
    _assert_common_fields(data, "ScannerUnit")
    assert isinstance(data["scanner_code"], str) and len(data["scanner_code"]) > 0
    assert isinstance(data["capacity_pages_per_session"], int) and data["capacity_pages_per_session"] >= 1
    assert data["status"] in ("AVAILABLE", "MAINTENANCE")


def assert_shelf_slot(data: dict):
    _assert_common_fields(data, "ShelfSlot")
    assert isinstance(data["shelf_code"], str) and len(data["shelf_code"]) > 0
    assert data["zone"] in ("GENERAL", "VAULT")
    assert isinstance(data["capacity_grams"], int) and data["capacity_grams"] >= 1
    assert isinstance(data["occupied_weight_grams"], int) and data["occupied_weight_grams"] >= 0


def assert_shelf_assignment(data: dict):
    _assert_common_fields(data, "ShelfAssignment")
    assert is_valid_uuid(data["box_id"])
    assert is_valid_uuid(data["shelf_slot_id"])
    assert is_iso8601_timestamp(data["placed_at"])
    assert data.get("released_at") is None or is_iso8601_timestamp(data["released_at"])
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert is_valid_uuid(data["batch_id"])
    assert is_valid_uuid(data["client_id"])
    assert data["status"] in ("DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "VOID")
    assert isinstance(data["page_subtotal_cents"], int) and data["page_subtotal_cents"] >= 0
    assert isinstance(data["storage_subtotal_cents"], int) and data["storage_subtotal_cents"] >= 0
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert data["total_cents"] == data["page_subtotal_cents"] + data["storage_subtotal_cents"], (
        f"total_cents {data['total_cents']} != page {data['page_subtotal_cents']} + storage {data['storage_subtotal_cents']}"
    )
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0
    assert data.get("issued_at") is None or is_iso8601_timestamp(data["issued_at"])
