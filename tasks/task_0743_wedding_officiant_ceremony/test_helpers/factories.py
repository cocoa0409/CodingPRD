"""Payload factories — one per entity, input fields only (PRD Section 3).

Only fields the client supplies are included. System- and computed-source fields
(status, quoted_*, version, ...) are never sent in a create payload.
"""


def create_officiant_payload(**overrides) -> dict:
    """POST /officiants input (PRD Section 3.1).

    Required: full_name, email, styles, denomination, certified_jurisdictions.
    Optional (server default): travel_buffer_minutes (180), max_active_holds (5).
    """
    payload = {
        "full_name": "Test Officiant",
        "email": "officiant@example.com",
        "styles": ["SECULAR"],
        "denomination": "CIVIL",
        "certified_jurisdictions": ["CA"],
    }
    payload.update(overrides)
    return payload


def create_couple_payload(**overrides) -> dict:
    """POST /couples input (PRD Section 3.1)."""
    payload = {
        "partner_one_name": "Partner One",
        "partner_two_name": "Partner Two",
        "email": "couple@example.com",
        "phone": "555-0100",
    }
    payload.update(overrides)
    return payload


def create_package_payload(**overrides) -> dict:
    """POST /packages input (PRD Section 3.1)."""
    payload = {
        "name": "Classic",
        "tier": "CLASSIC",
        "base_price_cents": 200000,
        "deposit_pct": 0.30,
    }
    payload.update(overrides)
    return payload


def create_venue_payload(**overrides) -> dict:
    """POST /venues input (PRD Section 3.1)."""
    payload = {
        "name": "Rose Garden",
        "jurisdiction": "CA",
        "address": "1 Main St",
    }
    payload.update(overrides)
    return payload


def create_booking_payload(officiant_id, couple_id, package_id, venue_id, **overrides) -> dict:
    """POST /bookings input (PRD Section 3.2).

    addon_codes is optional and defaults to an empty list.
    """
    payload = {
        "officiant_id": officiant_id,
        "couple_id": couple_id,
        "package_id": package_id,
        "venue_id": venue_id,
        "ceremony_start": "2026-09-01T15:00:00Z",
        "ceremony_end": "2026-09-01T16:00:00Z",
        "travel_distance_km": 10,
        "required_style": "SECULAR",
    }
    payload.update(overrides)
    return payload


def create_date_hold_payload(booking_id, expected_officiant_version, **overrides) -> dict:
    """POST /date-holds input (PRD Sections 2.7, 3.3)."""
    payload = {
        "booking_id": booking_id,
        "expected_officiant_version": expected_officiant_version,
    }
    payload.update(overrides)
    return payload


def create_ceremony_script_payload(booking_id, **overrides) -> dict:
    """POST /ceremony-scripts input (PRD Section 3.4).

    readings and ritual_elements are optional and default to empty lists.
    """
    payload = {
        "booking_id": booking_id,
        "opening_remarks": "Welcome",
        "vow_format": "PERSONAL",
        "closing_blessing": "Go well",
    }
    payload.update(overrides)
    return payload


def create_rehearsal_payload(booking_id, venue_id, **overrides) -> dict:
    """POST /rehearsals input (PRD Section 3.5)."""
    payload = {
        "booking_id": booking_id,
        "venue_id": venue_id,
        "rehearsal_start": "2026-08-31T18:00:00Z",
        "rehearsal_end": "2026-08-31T19:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_marriage_license_payload(booking_id, **overrides) -> dict:
    """POST /marriage-licenses input (PRD Section 3.6)."""
    payload = {
        "booking_id": booking_id,
        "jurisdiction": "CA",
        "license_number": "CA-777",
        "issued_date": "2026-02-20T00:00:00Z",
        "expiry_date": "2026-12-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_review_payload(booking_id, **overrides) -> dict:
    """POST /reviews input (PRD Section 3.9)."""
    payload = {
        "booking_id": booking_id,
        "rating": 5,
        "text": "Wonderful ceremony",
    }
    payload.update(overrides)
    return payload
