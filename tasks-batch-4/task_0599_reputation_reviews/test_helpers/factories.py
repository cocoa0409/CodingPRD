"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS


def create_business_payload(**overrides) -> dict:
    payload = {"name": TEST_DEFAULTS["BUSINESS_NAME"]}
    payload.update(overrides)
    return payload


def create_location_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["LOCATION_NAME"],
        "nap_name": TEST_DEFAULTS["NAP_NAME"],
        "nap_address": TEST_DEFAULTS["NAP_ADDRESS"],
        "nap_phone": TEST_DEFAULTS["NAP_PHONE"],
    }
    payload.update(overrides)
    return payload


def nap_payload(**overrides) -> dict:
    """Body of PUT /reputation/locations/{id}/nap — all three parts are required."""
    payload = {
        "nap_name": TEST_DEFAULTS["NAP_NAME"],
        "nap_address": TEST_DEFAULTS["NAP_ADDRESS"],
        "nap_phone": TEST_DEFAULTS["NAP_PHONE"],
    }
    payload.update(overrides)
    return payload


def create_listing_payload(site: str = "GOOGLE", **overrides) -> dict:
    """A listing whose published NAP matches the canonical record by default."""
    payload = {
        "site": site,
        "external_listing_id": f"{site[0].lower()}-1",
        "listed_nap_name": TEST_DEFAULTS["NAP_NAME"],
        "listed_nap_address": TEST_DEFAULTS["NAP_ADDRESS"],
        "listed_nap_phone": TEST_DEFAULTS["NAP_PHONE"],
    }
    payload.update(overrides)
    return payload


def create_contact_payload(**overrides) -> dict:
    payload = {"full_name": "E One", "email": "e1@example.com"}
    payload.update(overrides)
    return payload


def email_contact_payload(full_name: str, email: str, **overrides) -> dict:
    payload = {"full_name": full_name, "email": email, "email_consent": True}
    payload.update(overrides)
    return payload


def sms_contact_payload(full_name: str, phone: str, **overrides) -> dict:
    payload = {"full_name": full_name, "phone": phone, "sms_consent": True}
    payload.update(overrides)
    return payload


def create_template_payload(**overrides) -> dict:
    payload = {
        "name": "Praise",
        "body": "Thanks for the kind words!",
        "min_rating": 4,
        "max_rating": 5,
    }
    payload.update(overrides)
    return payload


def create_campaign_payload(expected_location_version: int, **overrides) -> dict:
    payload = {
        "name": "Spring Asks",
        "channel": "EMAIL",
        "message_body": TEST_DEFAULTS["MESSAGE_BODY"],
        "send_window_start": TEST_DEFAULTS["SEND_WINDOW_START"],
        "send_window_end": TEST_DEFAULTS["SEND_WINDOW_END"],
        "daily_send_cap": 10,
        "credits_allocated": 10,
        "expected_location_version": expected_location_version,
    }
    payload.update(overrides)
    return payload


def ingest_review_payload(**overrides) -> dict:
    payload = {
        "site": "GOOGLE",
        "external_review_id": "g-r1",
        "author_name": "Ann",
        "rating": 5,
        "text": "Superb",
        "posted_at": "2026-05-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_review_response_payload(expected_review_version: int, **overrides) -> dict:
    payload = {
        "body": "Thank you!",
        "expected_review_version": expected_review_version,
    }
    payload.update(overrides)
    return payload


def create_competitor_payload(**overrides) -> dict:
    payload = {"name": "Rival Dental", "site": "GOOGLE", "avg_rating": 4.20, "review_count": 80}
    payload.update(overrides)
    return payload


def create_widget_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def create_survey_payload(contact_id: str, **overrides) -> dict:
    payload = {"contact_id": contact_id}
    payload.update(overrides)
    return payload


def submit_survey_payload(nps_score: int, **overrides) -> dict:
    payload = {"nps_score": nps_score}
    payload.update(overrides)
    return payload
