"""Payload factories — one per entity, input fields only."""
import uuid


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def create_establishment_payload(**overrides) -> dict:
    payload = {"name": "Test Establishment", "jurisdiction": "CA-01"}
    payload.update(overrides)
    return payload


def create_inspector_payload(**overrides) -> dict:
    payload = {"full_name": "Test Inspector", "badge_number": _uniq("BADGE")}
    payload.update(overrides)
    return payload


def create_device_payload(establishment_id, **overrides) -> dict:
    payload = {
        "establishment_id": establishment_id,
        "device_type": "SCALE",
        "serial_number": _uniq("SN"),
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(device_id, inspector_id, expected_device_version, **overrides) -> dict:
    payload = {
        "device_id": device_id,
        "inspector_id": inspector_id,
        "inspection_type": "ACCURACY_TEST",
        "scheduled_start": "2026-03-02T09:00:00Z",
        "scheduled_end": "2026-03-02T10:00:00Z",
        "expected_device_version": expected_device_version,
    }
    payload.update(overrides)
    return payload


def create_test_reading_payload(applied_load, indicated_value) -> dict:
    return {"applied_load": applied_load, "indicated_value": indicated_value}


def create_audit_item_payload(item_sku, posted_price_cents, scanned_price_cents) -> dict:
    return {
        "item_sku": item_sku,
        "posted_price_cents": posted_price_cents,
        "scanned_price_cents": scanned_price_cents,
    }


def create_complaint_payload(device_id, **overrides) -> dict:
    payload = {
        "device_id": device_id,
        "complainant_name": "Test Complainant",
        "description": "Device reads inaccurately.",
    }
    payload.update(overrides)
    return payload
