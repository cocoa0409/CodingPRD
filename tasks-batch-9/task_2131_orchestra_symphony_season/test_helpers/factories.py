"""Payload factories — one per entity, input fields only."""

import itertools

_email_counter = itertools.count(1)


DEFAULTS = {
    "SEASON_NAME": "2027 Season",
    "FISCAL_YEAR": 2027,
    "RENEWAL_DEADLINE_UTC": "2026-10-01T00:00:00Z",
    "BASE_TICKET_PRICE_CENTS": 6000,
    "LOYALTY_DISCOUNT_BP": 500,
    "VENUE_NAME": "Grand Hall",
    "CHANGEOVER_BUFFER_MINUTES": 60,
    "SCALE_SERVICE_FEE_CENTS": 20000,
    "CONCERT_TITLE": "Opening Night",
    "PROGRAM_MINUTES": 100,
    "ARTIST_NAME": "Mira Halvorsen",
    "OFFERED_FEE_CENTS": 800000,
    "MUSICIAN_NAME": "Pia Solberg",
    "ADVERTISER_NAME": "Kestrel Motors",
}


def unique_email(prefix: str = "patron") -> str:
    return f"{prefix}{next(_email_counter)}@patron.test"


def create_season_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SEASON_NAME"],
        "fiscal_year": DEFAULTS["FISCAL_YEAR"],
        "renewal_deadline_utc": DEFAULTS["RENEWAL_DEADLINE_UTC"],
        "base_ticket_price_cents": DEFAULTS["BASE_TICKET_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_venue_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["VENUE_NAME"],
        "changeover_buffer_minutes": DEFAULTS["CHANGEOVER_BUFFER_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_section_payload(venue_id: str, **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "name": "ORCHESTRA",
        "capacity": 100,
        "price_multiplier_bp": 15000,
        "donor_priority_rank": 1,
    }
    payload.update(overrides)
    return payload


def orchestra_section_payload(venue_id: str, **overrides) -> dict:
    """ORCHESTRA: capacity 100, 15000bp multiplier, donor rank 1."""
    return create_section_payload(venue_id, **overrides)


def balcony_section_payload(venue_id: str, **overrides) -> dict:
    """BALCONY: capacity 50, 8000bp multiplier, donor rank 4, no priority floor."""
    payload = {
        "venue_id": venue_id,
        "name": "BALCONY",
        "capacity": 50,
        "price_multiplier_bp": 8000,
        "donor_priority_rank": 4,
        "min_renewal_priority_score": 0,
    }
    payload.update(overrides)
    return payload


def create_union_agreement_payload(season_id: str, **overrides) -> dict:
    payload = {
        "season_id": season_id,
        "scale_service_fee_cents": DEFAULTS["SCALE_SERVICE_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_concert_payload(season_id: str, venue_id: str, **overrides) -> dict:
    payload = {
        "season_id": season_id,
        "venue_id": venue_id,
        "title": DEFAULTS["CONCERT_TITLE"],
        "performance_start_utc": "2026-11-05T19:30:00Z",
        "performance_end_utc": "2026-11-05T21:30:00Z",
        "program_minutes": DEFAULTS["PROGRAM_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_guest_contract_payload(concert_id: str, **overrides) -> dict:
    payload = {
        "concert_id": concert_id,
        "artist_name": DEFAULTS["ARTIST_NAME"],
        "role_type": "SOLOIST",
        "offered_fee_cents": DEFAULTS["OFFERED_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_musician_payload(**overrides) -> dict:
    payload = {"full_name": DEFAULTS["MUSICIAN_NAME"], "instrument": "VIOLIN"}
    payload.update(overrides)
    return payload


def create_rehearsal_payload(concert_id: str, venue_id: str, **overrides) -> dict:
    payload = {
        "concert_id": concert_id,
        "venue_id": venue_id,
        "service_type": "REHEARSAL",
        "scheduled_start_utc": "2026-11-04T14:00:00Z",
        "scheduled_end_utc": "2026-11-04T15:00:00Z",
        "minimum_complement": 0,
        "break_minutes": 0,
    }
    payload.update(overrides)
    return payload


def create_engagement_payload(musician_id: str, **overrides) -> dict:
    payload = {"musician_id": musician_id}
    payload.update(overrides)
    return payload


def create_patron_payload(**overrides) -> dict:
    payload = {"full_name": "Noel Vance", "email": unique_email("noel")}
    payload.update(overrides)
    return payload


def create_subscription_payload(
    patron_id: str, season_id: str, seat_section_id: str, concert_ids, **overrides
) -> dict:
    payload = {
        "patron_id": patron_id,
        "season_id": season_id,
        "seat_section_id": seat_section_id,
        "seat_count": 1,
        "concert_ids": list(concert_ids),
    }
    payload.update(overrides)
    return payload


def renew_subscription_payload(
    season_id: str, concert_ids, expected_package_version: int, **overrides
) -> dict:
    payload = {
        "season_id": season_id,
        "concert_ids": list(concert_ids),
        "expected_package_version": expected_package_version,
    }
    payload.update(overrides)
    return payload


def create_ticket_order_payload(
    concert_id: str,
    patron_id: str,
    seat_section_id: str,
    expected_concert_version: int,
    **overrides,
) -> dict:
    payload = {
        "concert_id": concert_id,
        "patron_id": patron_id,
        "seat_section_id": seat_section_id,
        "seat_count": 1,
        "expected_concert_version": expected_concert_version,
    }
    payload.update(overrides)
    return payload


def create_ad_booking_payload(season_id: str, **overrides) -> dict:
    payload = {
        "season_id": season_id,
        "advertiser_name": DEFAULTS["ADVERTISER_NAME"],
        "ad_size": "QUARTER_PAGE",
        "placement": "RUN_OF_BOOK",
        "insertion_count": 2,
    }
    payload.update(overrides)
    return payload
