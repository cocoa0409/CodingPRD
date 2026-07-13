"""Payload factories — one per entity, input fields only."""
import uuid


def unique_email(prefix="user"):
    return f"{prefix}_{uuid.uuid4().hex[:12]}@example.com"


def create_user_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email(),
        "full_name": "Test User",
        "phone": "5550000",
    }
    defaults.update(overrides)
    return defaults


def create_verification_payload(**overrides) -> dict:
    defaults = {
        "document_type": "PASSPORT",
        "document_ref": "DOC-REF-1",
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(owner_id, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "title": "Test Camera",
        "category": "camera",
        "declared_value_cents": 90000,
        "base_daily_rate_cents": 10000,
        "deposit_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(listing_id, renter_id, start_date, end_date,
                           expected_listing_version, **overrides) -> dict:
    defaults = {
        "listing_id": listing_id,
        "renter_id": renter_id,
        "start_date": start_date,
        "end_date": end_date,
        "expected_listing_version": expected_listing_version,
    }
    defaults.update(overrides)
    return defaults


def create_handoff_payload(type, slot_start, slot_end, **overrides) -> dict:
    defaults = {
        "type": type,
        "slot_start": slot_start,
        "slot_end": slot_end,
    }
    defaults.update(overrides)
    return defaults


def create_condition_report_payload(phase, **overrides) -> dict:
    defaults = {
        "phase": phase,
        "photo_urls": ["photo-url-1"],
        "recorded_by": "OWNER",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(claim_type, claimed_amount_cents, **overrides) -> dict:
    defaults = {
        "claim_type": claim_type,
        "claimed_amount_cents": claimed_amount_cents,
        "description": "condition issue",
    }
    defaults.update(overrides)
    return defaults


def create_rating_payload(ratee_id, direction, score, **overrides) -> dict:
    defaults = {
        "ratee_id": ratee_id,
        "direction": direction,
        "score": score,
    }
    defaults.update(overrides)
    return defaults
