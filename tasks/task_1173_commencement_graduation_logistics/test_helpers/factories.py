"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS


def create_venue_payload(**overrides) -> dict:
    defaults = {
        "name": "Main Arena",
        "address": "1 College Ave",
        "total_capacity": TEST_DEFAULTS["VENUE_CAPACITY"],
        "accessible_capacity": TEST_DEFAULTS["VENUE_ACCESSIBLE"],
        "indoor": True,
    }
    defaults.update(overrides)
    return defaults


def create_ceremony_payload(venue_id: str, **overrides) -> dict:
    defaults = {
        "name": "Spring Commencement",
        "ceremony_date": TEST_DEFAULTS["CEREMONY_DATE"],
        "venue_id": venue_id,
        "ticket_ratio": TEST_DEFAULTS["TICKET_RATIO"],
        "guest_ticket_base_cap": TEST_DEFAULTS["GUEST_TICKET_BASE_CAP"],
        "honor_bonus_tickets": TEST_DEFAULTS["HONOR_BONUS_TICKETS"],
        "pronunciation_deadline": TEST_DEFAULTS["PRONUNCIATION_DEADLINE"],
        "ticket_request_deadline": TEST_DEFAULTS["TICKET_REQUEST_DEADLINE"],
        "regalia_order_deadline": TEST_DEFAULTS["REGALIA_ORDER_DEADLINE"],
    }
    defaults.update(overrides)
    return defaults


def create_graduate_payload(ceremony_id: str, **overrides) -> dict:
    defaults = {
        "ceremony_id": ceremony_id,
        "full_name": "Test Graduate",
        "email": "graduate@x.edu",
        "institutional_gpa_credits": 45,
        "institutional_quality_points": 160.0,
        "transfer_gpa_credits": 0,
        "transfer_quality_points": 0,
        "credits_completed": 120,
        "credits_required": 120,
        "outstanding_hold_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(**overrides) -> dict:
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def create_ticket_request_payload(requested_count: int, expected_ticket_allocation_version: int) -> dict:
    return {
        "requested_count": requested_count,
        "expected_ticket_allocation_version": expected_ticket_allocation_version,
    }


def create_regalia_order_payload(items=None, **overrides) -> dict:
    defaults = {
        "items": items if items is not None else [
            {"item_type": "GOWN", "size": "M", "quantity": 1, "unit_price_cents": 10000}
        ],
    }
    defaults.update(overrides)
    return defaults


def create_seat_assignment_payload(ceremony_id: str, graduate_id: str, **overrides) -> dict:
    defaults = {
        "ceremony_id": ceremony_id,
        "graduate_id": graduate_id,
        "section": "A",
        "row_label": "1",
        "seat_number": 1,
    }
    defaults.update(overrides)
    return defaults


def create_reader_card_payload(phonetic_spelling: str = "TEH-st GRAD-yoo-it", **overrides) -> dict:
    defaults = {"phonetic_spelling": phonetic_spelling}
    defaults.update(overrides)
    return defaults


def create_rehearsal_session_payload(venue_id: str, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "start_utc": "2026-05-25T10:00:00Z",
        "end_utc": "2026-05-25T11:00:00Z",
        "capacity": 30,
    }
    defaults.update(overrides)
    return defaults


def create_accommodation_request_payload(ceremony_id: str, request_type: str = "WHEELCHAIR_SEAT", **overrides) -> dict:
    defaults = {
        "ceremony_id": ceremony_id,
        "request_type": request_type,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_contract_payload(vendor_user_id: str = "vendor-1", **overrides) -> dict:
    defaults = {
        "vendor_type": "LIVESTREAM",
        "vendor_user_id": vendor_user_id,
        "coverage_start_utc": "2026-06-01T12:00:00Z",
        "coverage_end_utc": "2026-06-01T15:00:00Z",
        "setup_buffer_minutes": 30,
        "fee_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_print_batch_payload(**overrides) -> dict:
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def create_queue_diploma_payload(graduate_id: str, **overrides) -> dict:
    defaults = {"graduate_id": graduate_id}
    defaults.update(overrides)
    return defaults
