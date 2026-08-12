"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_client_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Client",
        "hipaa_covered": False,
    }
    defaults.update(overrides)
    return defaults


def create_service_agreement_payload(**overrides) -> dict:
    defaults = {
        "price_tier": "STANDARD",
        "rush_multiplier": TEST_DEFAULTS["RUSH_MULTIPLIER"],
        "storage_free_days": TEST_DEFAULTS["STORAGE_FREE_DAYS"],
        "storage_daily_rate_cents": TEST_DEFAULTS["STORAGE_DAILY_RATE_CENTS"],
        "retention_days": TEST_DEFAULTS["RETENTION_DAYS"],
        "max_boxes_per_batch": TEST_DEFAULTS["MAX_BOXES_PER_BATCH"],
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(**overrides) -> dict:
    defaults = {
        "client_id": "",
        "priority": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_box_payload(**overrides) -> dict:
    defaults = {
        "box_label": "BX-1",
        "intake_weight_grams": 600,
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(**overrides) -> dict:
    defaults = {
        "doc_type": "CONTRACT",
        "pages": 100,
        "contains_phi": False,
        "ocr_confidence": 95,
    }
    defaults.update(overrides)
    return defaults


def create_scanner_unit_payload(**overrides) -> dict:
    defaults = {
        "scanner_code": "SCN-1",
        "capacity_pages_per_session": TEST_DEFAULTS["SCANNER_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_shelf_slot_payload(**overrides) -> dict:
    defaults = {
        "shelf_code": "SH-G1",
        "zone": "GENERAL",
        "capacity_grams": TEST_DEFAULTS["SHELF_CAPACITY_GRAMS"],
    }
    defaults.update(overrides)
    return defaults


def create_shelf_assignment_payload(**overrides) -> dict:
    defaults = {
        "shelf_slot_id": "",
    }
    defaults.update(overrides)
    return defaults


def create_custody_event_payload(**overrides) -> dict:
    defaults = {
        "to_stage": "PREP",
    }
    defaults.update(overrides)
    return defaults


def create_page_log_payload(**overrides) -> dict:
    defaults = {
        "document_id": "",
        "pages": 1,
    }
    defaults.update(overrides)
    return defaults


def create_index_record_payload(**overrides) -> dict:
    defaults = {
        "metadata_json": {
            "title": "T",
            "record_date": "2026-01-01",
            "subject": "S",
        },
        "ocr_text_ref": "ocr://ref",
    }
    defaults.update(overrides)
    return defaults


def create_access_grant_payload(**overrides) -> dict:
    defaults = {
        "batch_id": "",
        "scope": "FULL_IMAGE",
        "expires_at": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_destruction_certificate_payload(**overrides) -> dict:
    defaults = {
        "witness_user_id": "wit-1",
        "method": "SHRED",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 1,
    }
    defaults.update(overrides)
    return defaults


def create_void_invoice_payload(**overrides) -> dict:
    defaults = {
        "void_reason": "void",
    }
    defaults.update(overrides)
    return defaults


def create_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
