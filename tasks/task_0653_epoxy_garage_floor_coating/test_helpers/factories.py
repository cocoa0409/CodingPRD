"""Payload factories — one per entity, input fields only.

Each factory provides PRD-faithful defaults and accepts **overrides.
Only fields the client supplies (source: input) appear here; computed and
system fields are minted by the server.
"""

DEFAULTS = {
    "EMAIL": "owner@example.com",
    "FULL_NAME": "Test Owner",
    "SITE_ZIP": "94016",
}


# ---- Catalog entities ----
def create_coating_system_payload(**overrides) -> dict:
    payload = {
        "name": "Test Coating System",
        "family": "FLAKE",
        "sku": "FLAKE_STANDARD",
    }
    payload.update(overrides)
    return payload


def create_color_option_payload(coating_system_id, **overrides) -> dict:
    payload = {
        "coating_system_id": coating_system_id,
        "name": "Test Color",
        "flake_blend_code": "TC-01",
    }
    payload.update(overrides)
    return payload


def create_financing_plan_payload(**overrides) -> dict:
    payload = {
        "name": "Test Plan",
        "apr_bps": 999,
        "term_months": 36,
        "min_principal_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_crew_payload(**overrides) -> dict:
    payload = {
        "name": "Test Crew",
        "metallic_certified": False,
        "max_sqft_per_day": 1000,
    }
    payload.update(overrides)
    return payload


# ---- Customer / Project ----
def create_customer_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["FULL_NAME"],
        "email": DEFAULTS["EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_project_payload(customer_id, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "site_zip": DEFAULTS["SITE_ZIP"],
    }
    payload.update(overrides)
    return payload


def create_assessment_payload(**overrides) -> dict:
    payload = {
        "measured_sqft": 600,
        "oil_stain_pct": 50,
        "crack_density": 20,
        "crack_linear_ft": 15,
        "spalling": True,
        "moisture_pct": 30,
    }
    payload.update(overrides)
    return payload


def create_quote_payload(assessment_id, coating_system_id, color_option_id,
                         install_season="STANDARD", **overrides) -> dict:
    payload = {
        "assessment_id": assessment_id,
        "coating_system_id": coating_system_id,
        "color_option_id": color_option_id,
        "install_season": install_season,
    }
    payload.update(overrides)
    return payload


def create_install_job_payload(crew_id, install_date, **overrides) -> dict:
    payload = {
        "crew_id": crew_id,
        "install_date": install_date,
    }
    payload.update(overrides)
    return payload


def complete_install_payload(as_measured_sqft=600, as_measured_crack_ft=15,
                             **overrides) -> dict:
    payload = {
        "as_measured_sqft": as_measured_sqft,
        "as_measured_crack_ft": as_measured_crack_ft,
    }
    payload.update(overrides)
    return payload


def create_claim_payload(defect_type="PEEL", **overrides) -> dict:
    payload = {"defect_type": defect_type}
    payload.update(overrides)
    return payload


def create_referral_payload(referrer_customer_id, referred_customer_id,
                            project_id, **overrides) -> dict:
    payload = {
        "referrer_customer_id": referrer_customer_id,
        "referred_customer_id": referred_customer_id,
        "project_id": project_id,
    }
    payload.update(overrides)
    return payload
