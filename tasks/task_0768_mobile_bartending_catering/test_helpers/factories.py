"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Defaults reflect the canonical CLASSIC package and
the 80-guest / 5h event used throughout the design indices; every value is
overridable via **overrides.
"""

# Canonical timestamps (ISO 8601 UTC) reused across setups.
DEFAULT_EVENT_START = "2026-06-01T18:00:00Z"
DEFAULT_EVENT_END = "2026-06-01T23:00:00Z"
DEFAULT_CERT_EXPIRY = "2027-01-01T00:00:00Z"


def create_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Ada Host",
        "email": "ada@x.com",
        "phone": "555-1",
        "home_state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(**overrides) -> dict:
    """CLASSIC package: base 150000, included 50 guests / 4 hours,
    per_guest 1800, per_hour 25000, 1.25 drinks/guest/hr, 50 guests/bartender."""
    defaults = {
        "tier": "CLASSIC",
        "name": "Classic Cocktail",
        "base_price_cents": 150000,
        "included_guest_count": 50,
        "per_guest_overage_cents": 1800,
        "included_hours": 4,
        "min_hours": 3,
        "per_hour_overage_cents": 25000,
        "drinks_per_guest_per_hour": 1.25,
        "guests_per_bartender": 50,
    }
    defaults.update(overrides)
    return defaults


def create_bartender_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Ben Bar",
        "email": "ben@x.com",
        "certification_expiry": DEFAULT_CERT_EXPIRY,
        "hourly_rate_cents": 4000,
        "home_state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_bar_kit_payload(**overrides) -> dict:
    defaults = {
        "kit_name": "Full Bar A",
        "station_type": "FULL_BAR",
        "glassware_count": 200,
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(client_id, package_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "package_id": package_id,
        "title": "Gala",
        "venue_state_code": "CA",
        "venue_type": "INDOOR",
        "event_start": DEFAULT_EVENT_START,
        "event_end": DEFAULT_EVENT_END,
        "guest_count": 80,
    }
    defaults.update(overrides)
    return defaults


def create_compliance_review_payload(**overrides) -> dict:
    """All four attestations default to the compliant HOST_NO_SALE posture."""
    defaults = {
        "abc_model": "HOST_NO_SALE",
        "liquor_liability_insurance_verified": True,
        "host_alcohol_ownership_attested": True,
        "server_certification_verified": True,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(bartender_id, expected_event_version, **overrides) -> dict:
    defaults = {
        "bartender_id": bartender_id,
        "shift_start": "2026-06-01T17:00:00Z",
        "shift_end": "2026-06-01T23:30:00Z",
        "role_on_event": "BACK",
        "expected_event_version": expected_event_version,
    }
    defaults.update(overrides)
    return defaults


def create_kit_reservation_payload(kit_id, **overrides) -> dict:
    defaults = {
        "kit_id": kit_id,
        "reserve_start": "2026-06-01T16:00:00Z",
        "reserve_end": "2026-06-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_menu_item_payload(**overrides) -> dict:
    defaults = {
        "name": "House Margarita",
        "drink_type": "COCKTAIL",
        "spirit_base": "TEQUILA",
        "abv_pct": 13.5,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(payment_type, amount_cents, **overrides) -> dict:
    defaults = {
        "payment_type": payment_type,
        "amount_cents": amount_cents,
        "method": "CARD",
    }
    defaults.update(overrides)
    return defaults


def create_breakage_report_payload(kit_id, items_broken, items_returned, **overrides) -> dict:
    defaults = {
        "kit_id": kit_id,
        "items_broken": items_broken,
        "items_returned": items_returned,
    }
    defaults.update(overrides)
    return defaults
