"""Payload factories — one per entity, input fields only.

Each factory returns the request body for a create/hold call; only
source=input fields appear. Optional fields with PRD defaults are omitted
unless overridden.
"""

DEFAULTS = {
    "SEASON_NAME": "Test Season",
    "RENEWAL_OPENS_AT": "2026-05-01T00:00:00Z",
    "RENEWAL_CLOSES_AT": "2026-05-15T00:00:00Z",
    "BASE_SUBSCRIPTION_FEE_CENTS": 20000,
    "PRODUCTION_TITLE": "Test Production",
    "VENUE_NAME": "Test Venue",
    "STARTS_AT": "2026-07-01T19:30:00Z",
    "ON_SALE_AT": "2026-06-01T00:00:00Z",
}


def create_season_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SEASON_NAME"],
        "renewal_window_opens_at": DEFAULTS["RENEWAL_OPENS_AT"],
        "renewal_window_closes_at": DEFAULTS["RENEWAL_CLOSES_AT"],
        "base_subscription_fee_cents": DEFAULTS["BASE_SUBSCRIPTION_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_production_payload(season_id, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "title": DEFAULTS["PRODUCTION_TITLE"],
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["VENUE_NAME"]}
    defaults.update(overrides)
    return defaults


def create_seat_payload(venue_id, section="ORCH", row_label="A", seat_number=1,
                        price_tier="STANDARD", **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "section": section,
        "row_label": row_label,
        "seat_number": seat_number,
        "price_tier": price_tier,
    }
    defaults.update(overrides)
    return defaults


def create_performance_payload(production_id, venue_id, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "venue_id": venue_id,
        "starts_at": DEFAULTS["STARTS_AT"],
        "on_sale_at": DEFAULTS["ON_SALE_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_patron_payload(email="patron@example.com", full_name="Test Patron", **overrides) -> dict:
    defaults = {"email": email, "full_name": full_name}
    defaults.update(overrides)
    return defaults


def create_subscription_payload(season_id, patron_id, **overrides) -> dict:
    defaults = {"season_id": season_id, "patron_id": patron_id}
    defaults.update(overrides)
    return defaults


def create_subscription_seat_payload(subscription_id, seat_id, **overrides) -> dict:
    defaults = {"subscription_id": subscription_id, "seat_id": seat_id}
    defaults.update(overrides)
    return defaults


def create_ticket_payload(performance_id, seat_id, patron_id, origin,
                          expected_performance_version, **overrides) -> dict:
    defaults = {
        "performance_id": performance_id,
        "seat_id": seat_id,
        "patron_id": patron_id,
        "origin": origin,
        "expected_performance_version": expected_performance_version,
    }
    defaults.update(overrides)
    return defaults


def create_donation_payload(patron_id, amount_cents, **overrides) -> dict:
    defaults = {"patron_id": patron_id, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_exchange_payload(original_ticket_id, target_performance_id, target_seat_id,
                            mode, **overrides) -> dict:
    defaults = {
        "original_ticket_id": original_ticket_id,
        "target_performance_id": target_performance_id,
        "target_seat_id": target_seat_id,
        "mode": mode,
    }
    defaults.update(overrides)
    return defaults


def create_audition_payload(production_id, applicant_name="Test Applicant",
                            role_applied_for="Lead", **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "applicant_name": applicant_name,
        "role_applied_for": role_applied_for,
    }
    defaults.update(overrides)
    return defaults
