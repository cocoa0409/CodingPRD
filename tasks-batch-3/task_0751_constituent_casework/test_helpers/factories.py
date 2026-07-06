"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "REP_NAME": "Rep Test",
    "OFFICE_EMAIL": "office@leg.gov",
    "CON_NAME": "Test Constituent",
    "CON_EMAIL": "constituent@example.com",
    "CON_ADDRESS": "1 Main St",
    "AGENCY_NAME": "Test Agency",
    "JURISDICTION": "US",
    "TEMPLATE_BODY": "Dear constituent, ...",
    "VENUE_NAME": "Test Hall",
    "EVENT_TITLE": "Town Hall",
    "NEWSLETTER_SUBJECT": "Office Update",
    "NEWSLETTER_BODY": "Hello constituents",
}


def create_representative_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["REP_NAME"],
        "chamber": "HOUSE",
        "district_name": "CA-12",
        "state_code": "CA",
        "office_email": DEFAULTS["OFFICE_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_constituent_payload(representative_id, **overrides) -> dict:
    defaults = {
        "representative_id": representative_id,
        "full_name": DEFAULTS["CON_NAME"],
        "email": DEFAULTS["CON_EMAIL"],
        "address": DEFAULTS["CON_ADDRESS"],
    }
    defaults.update(overrides)
    return defaults


def create_agency_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["AGENCY_NAME"],
        "jurisdiction": DEFAULTS["JURISDICTION"],
    }
    defaults.update(overrides)
    return defaults


def create_template_payload(category, response_window_hours=100, **overrides) -> dict:
    defaults = {
        "category": category,
        "body_template": DEFAULTS["TEMPLATE_BODY"],
        "response_window_hours": response_window_hours,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(constituent_id, category="OTHER", **overrides) -> dict:
    defaults = {
        "constituent_id": constituent_id,
        "subject": "Inquiry",
        "description": "Details of the inquiry",
        "category": category,
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(capacity=50, **overrides) -> dict:
    defaults = {
        "name": DEFAULTS["VENUE_NAME"],
        "capacity": capacity,
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(representative_id, venue_id, start_at, end_at, capacity=10, **overrides) -> dict:
    defaults = {
        "representative_id": representative_id,
        "venue_id": venue_id,
        "title": DEFAULTS["EVENT_TITLE"],
        "start_at": start_at,
        "end_at": end_at,
        "capacity": capacity,
    }
    defaults.update(overrides)
    return defaults


def create_newsletter_payload(page_count=1, **overrides) -> dict:
    defaults = {
        "subject": DEFAULTS["NEWSLETTER_SUBJECT"],
        "body": DEFAULTS["NEWSLETTER_BODY"],
        "page_count": page_count,
    }
    defaults.update(overrides)
    return defaults
