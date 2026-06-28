"""Payload factories — one per entity, input fields only."""


def create_homeowner_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Owner",
        "email": "owner@example.com",
        "credit_band": "PRIME",
    }
    defaults.update(overrides)
    return defaults


def create_job_payload(homeowner_id, **overrides) -> dict:
    defaults = {
        "homeowner_id": homeowner_id,
        "property_address": "1 Test St",
        "structure_type": "CRAWLSPACE",
        "footprint_sqft": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Crew",
        "home_region": "NORTH",
        "daily_capacity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    defaults = {
        "moisture_pct": 50,
        "structural_findings_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(**overrides) -> dict:
    # All scope flags default to false / NONE per PRD §3.4; tests pass only what they exercise.
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_install_order_payload(scheduled_start, scheduled_end, expected_job_version,
                                 **overrides) -> dict:
    defaults = {
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "expected_job_version": expected_job_version,
    }
    defaults.update(overrides)
    return defaults


def create_crew_booking_payload(crew_id, install_order_id, window_start, window_end,
                                **overrides) -> dict:
    defaults = {
        "crew_id": crew_id,
        "install_order_id": install_order_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_financing_application_payload(job_id, quote_id, term_months, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "quote_id": quote_id,
        "term_months": term_months,
    }
    defaults.update(overrides)
    return defaults


def create_service_visit_payload(visit_type, scheduled_for, **overrides) -> dict:
    defaults = {
        "visit_type": visit_type,
        "scheduled_for": scheduled_for,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(job_id, warranty_id, category, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "warranty_id": warranty_id,
        "category": category,
        "description": "Test claim description",
    }
    defaults.update(overrides)
    return defaults


def create_foundation_referral_payload(inspection_id, partner_name="SolidGround",
                                       **overrides) -> dict:
    defaults = {
        "inspection_id": inspection_id,
        "partner_name": partner_name,
    }
    defaults.update(overrides)
    return defaults
