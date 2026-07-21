"""Payload factories — one per entity, input fields only."""
import uuid


def _unique_email(prefix="user"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def create_host_payload(**overrides) -> dict:
    payload = {"display_name": "Test Host", "email": _unique_email("host")}
    payload.update(overrides)
    return payload


def create_guest_payload(**overrides) -> dict:
    payload = {"display_name": "Test Guest", "email": _unique_email("guest")}
    payload.update(overrides)
    return payload


def create_listing_payload(host_id, **overrides) -> dict:
    payload = {
        "host_id": host_id,
        "title": "Test Listing",
        "site_type": "CABIN",
        "max_guests": 4,
        "base_nightly_rate_cents": 20000,
    }
    payload.update(overrides)
    return payload


def create_permit_payload(listing_id, **overrides) -> dict:
    payload = {
        "listing_id": listing_id,
        "permit_type": "STRUCTURE",
        "authority_name": "County",
    }
    payload.update(overrides)
    return payload


def create_seasonal_rate_payload(listing_id, start_date, end_date, nightly_rate_cents,
                                 **overrides) -> dict:
    payload = {
        "listing_id": listing_id,
        "start_date": start_date,
        "end_date": end_date,
        "nightly_rate_cents": nightly_rate_cents,
    }
    payload.update(overrides)
    return payload


def create_add_on_payload(listing_id, **overrides) -> dict:
    payload = {
        "listing_id": listing_id,
        "name": "Test Add-On",
        "category": "AMENITY",
        "pricing_unit": "PER_STAY",
        "price_cents": 1000,
    }
    payload.update(overrides)
    return payload


def create_slot_payload(add_on_id, slot_date, max_participants, **overrides) -> dict:
    payload = {
        "add_on_id": add_on_id,
        "slot_date": slot_date,
        "max_participants": max_participants,
    }
    payload.update(overrides)
    return payload


def create_booking_payload(listing_id, guest_id, check_in, check_out,
                           expected_listing_version, guest_count=2, **overrides) -> dict:
    payload = {
        "listing_id": listing_id,
        "guest_id": guest_id,
        "check_in": check_in,
        "check_out": check_out,
        "guest_count": guest_count,
        "expected_listing_version": expected_listing_version,
    }
    payload.update(overrides)
    return payload


def attach_add_on_payload(add_on_id, **overrides) -> dict:
    payload = {"add_on_id": add_on_id}
    payload.update(overrides)
    return payload


def create_review_payload(booking_id, rating=5, **overrides) -> dict:
    payload = {"booking_id": booking_id, "rating": rating}
    payload.update(overrides)
    return payload


def create_message_payload(booking_id, sender_role, body="Hello", **overrides) -> dict:
    payload = {"booking_id": booking_id, "sender_role": sender_role, "body": body}
    payload.update(overrides)
    return payload
