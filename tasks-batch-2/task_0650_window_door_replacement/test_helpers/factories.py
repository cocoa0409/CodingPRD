"""Payload factories — one per entity, input fields only.

Each factory accepts **overrides so tests can control the values they assert on,
and provides sensible defaults for everything else.
"""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix="ho") -> str:
    """A process-unique email; homeowner emails must be unique across homeowners."""
    return f"{prefix}-{next(_email_counter)}@example.com"


def create_homeowner_payload(**overrides) -> dict:
    """Homeowner input fields: full_name, email, property_zip, agi_band? (defaults STANDARD)."""
    defaults = {
        "full_name": "Test Homeowner",
        "email": unique_email(),
        "property_zip": "30301",  # first digit 3 -> CENTRAL_LIGHT
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(homeowner_id, **overrides) -> dict:
    defaults = {"homeowner_id": homeowner_id}
    defaults.update(overrides)
    return defaults


def create_consultation_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "consultant_id": "sc-1",
        "scheduled_at": "2026-04-02T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_opening_payload(consultation_id, **overrides) -> dict:
    defaults = {
        "consultation_id": consultation_id,
        "product_type": "CASEMENT",
        "width_in": 30,
        "height_in": 40,
        "glass_package": "LOWE_DUAL",
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(project_id, consultation_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "consultation_id": consultation_id,
    }
    defaults.update(overrides)
    return defaults


def accept_quote_payload(expected_quote_version, **overrides) -> dict:
    defaults = {"expected_quote_version": expected_quote_version}
    defaults.update(overrides)
    return defaults


def create_financing_payload(quote_id, **overrides) -> dict:
    defaults = {
        "quote_id": quote_id,
        "requested_amount_cents": 50_000,
        "term_months": 24,
    }
    defaults.update(overrides)
    return defaults


def decide_financing_payload(decision="APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Crew",
        "home_jurisdiction": "CENTRAL_LIGHT",
        "daily_capacity_openings": 5,
    }
    defaults.update(overrides)
    return defaults


def create_install_job_payload(project_id, crew_id, window_start, window_end, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "crew_id": crew_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(project_id, **overrides) -> dict:
    defaults = {"project_id": project_id}
    defaults.update(overrides)
    return defaults


def record_inspection_payload(result, **overrides) -> dict:
    defaults = {"result": result}
    defaults.update(overrides)
    return defaults


def create_service_ticket_payload(project_id, opening_id, category="WARRANTY", **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "opening_id": opening_id,
        "category": category,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(referrer_project_id, referred_project_id, **overrides) -> dict:
    defaults = {
        "referrer_project_id": referrer_project_id,
        "referred_project_id": referred_project_id,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
