"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import EVENT_ENDS_AT, EVENT_STARTS_AT, FOUND_AT


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": "Transit L&F",
        "program_type": "TRANSIT",
        "contact_email": "t@city.gov",
    }
    defaults.update(overrides)
    return defaults


def create_retention_policy_payload(program_id, expected_program_version, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "item_category": "ELECTRONICS",
        "value_tier": "LOW",
        "retention_days": 10,
        "disposal_method": "AUCTION",
        "expected_program_version": expected_program_version,
    }
    defaults.update(overrides)
    return defaults


def create_storage_location_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": "Cage T",
        "capacity_slots": 10,
        "supports_high_value": True,
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": "Depot Hall",
        "address": "1 Depot St",
        "insurance_cap_cents": 100000000,
    }
    defaults.update(overrides)
    return defaults


def create_claimant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Pat Owner",
        "email": "pat@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_item_payload(program_id, storage_location_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "storage_location_id": storage_location_id,
        "category": "ELECTRONICS",
        "declared_value_cents": 5000,
        "description": "earbuds",
        "found_at": FOUND_AT,
        "found_location": "Bus 12",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(item_id, claimant_id, expected_item_version, **overrides) -> dict:
    defaults = {
        "item_id": item_id,
        "claimant_id": claimant_id,
        "proof_serial": True,
        "proof_photo": False,
        "proof_receipt": False,
        "proof_description_detail": "BRIEF",
        "expected_item_version": expected_item_version,
    }
    defaults.update(overrides)
    return defaults


def create_resubmit_payload(**overrides) -> dict:
    defaults = {
        "proof_serial": True,
        "proof_photo": True,
        "proof_receipt": True,
        "proof_description_detail": "DETAILED",
    }
    defaults.update(overrides)
    return defaults


def create_inquiry_payload(**overrides) -> dict:
    defaults = {
        "contact_email": "a@x.com",
        "subject": "lost wallet",
        "message": "brown wallet on route 9",
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(**overrides) -> dict:
    defaults = {
        "agency_name": "CPD",
        "case_number": "C-100",
    }
    defaults.update(overrides)
    return defaults


def create_release_payload(**overrides) -> dict:
    defaults = {
        "handover_method": "IN_PERSON",
        "id_document_ref": "DL-999",
    }
    defaults.update(overrides)
    return defaults


def create_auction_event_payload(venue_id, program_id, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "program_id": program_id,
        "name": "Aug Sale",
        "starts_at": EVENT_STARTS_AT,
        "ends_at": EVENT_ENDS_AT,
    }
    defaults.update(overrides)
    return defaults


def create_auction_lot_payload(event_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "title": "Lot A",
    }
    defaults.update(overrides)
    return defaults
