"""Payload factories — one per entity, input fields only."""


def create_homeowner_payload(**overrides) -> dict:
    """Input fields for POST /homeowners. hoa_governed is optional (default false)."""
    defaults = {
        "email": "owner@example.com",
        "full_name": "Test Homeowner",
        "hoa_governed": False,
        "ground_snow_load_psf": 10,
        "design_wind_speed_mph": 90,
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(homeowner_id: str, **overrides) -> dict:
    """Input fields for POST /projects."""
    defaults = {
        "homeowner_id": homeowner_id,
        "address_line": "1 Test Way",
        "structure_type": "THREE_SEASON",
        "material": "ALUMINUM",
    }
    defaults.update(overrides)
    return defaults


def create_measurement_payload(project_id: str, **overrides) -> dict:
    """Input fields for POST /measurements. existing_slab is optional (default false)."""
    defaults = {
        "project_id": project_id,
        "width_in": 120,
        "depth_in": 144,
        "wall_height_in": 96,
        "existing_slab": True,
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(project_id: str, **overrides) -> dict:
    """Input fields for POST /quotes."""
    defaults = {"project_id": project_id}
    defaults.update(overrides)
    return defaults


def create_quote_accept_payload(expected_project_version: int, **overrides) -> dict:
    """Input fields for POST /quotes/{id}/accept (OCC field)."""
    defaults = {"expected_project_version": expected_project_version}
    defaults.update(overrides)
    return defaults


def create_financing_payload(project_id: str, quote_id: str, **overrides) -> dict:
    """Input fields for POST /financing-applications."""
    defaults = {
        "project_id": project_id,
        "quote_id": quote_id,
        "down_payment_cents": 0,
        "term_months": 12,
        "credit_score": 720,
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(project_id: str, **overrides) -> dict:
    """Input fields for POST /permit-applications."""
    defaults = {
        "project_id": project_id,
        "jurisdiction_code": "J1",
    }
    defaults.update(overrides)
    return defaults


def create_hoa_decision_payload(hoa_status: str, **overrides) -> dict:
    """Input fields for POST /permit-applications/{id}/hoa-decision."""
    defaults = {"hoa_status": hoa_status}
    defaults.update(overrides)
    return defaults


def create_permit_decide_payload(outcome: str, **overrides) -> dict:
    """Input fields for POST /permit-applications/{id}/decide."""
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_engineering_review_payload(permit_application_id: str, project_id: str,
                                       **overrides) -> dict:
    """Input fields for POST /engineering-reviews."""
    defaults = {
        "permit_application_id": permit_application_id,
        "project_id": project_id,
        "rated_wind_mph": 150,
        "rated_snow_psf": 45,
    }
    defaults.update(overrides)
    return defaults


def create_manufacture_order_payload(project_id: str, quote_id: str, **overrides) -> dict:
    """Input fields for POST /manufacture-orders."""
    defaults = {
        "project_id": project_id,
        "quote_id": quote_id,
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    """Input fields for POST /crews.
    certified_four_season (default false) and active (default true) are optional."""
    defaults = {
        "name": "Test Crew",
        "max_wind_mph": 40,
        "certified_four_season": False,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_install_job_payload(project_id: str, crew_id: str, scheduled_start: str,
                               scheduled_end: str, **overrides) -> dict:
    """Input fields for POST /install-jobs."""
    defaults = {
        "project_id": project_id,
        "crew_id": crew_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "forecast_wind_mph": 20,
    }
    defaults.update(overrides)
    return defaults


def create_weather_payload(weather_status: str, **overrides) -> dict:
    """Input fields for POST /install-jobs/{id}/weather."""
    defaults = {"weather_status": weather_status}
    defaults.update(overrides)
    return defaults


def create_inspection_payload(project_id: str, install_job_id: str, **overrides) -> dict:
    """Input fields for POST /inspections."""
    defaults = {
        "project_id": project_id,
        "install_job_id": install_job_id,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_fail_payload(punchlist_items: int, **overrides) -> dict:
    """Input fields for POST /inspections/{id}/fail."""
    defaults = {"punchlist_items": punchlist_items}
    defaults.update(overrides)
    return defaults


def create_clock_payload(to_iso8601: str, **overrides) -> dict:
    """Input fields for POST /_clock/set_current_utc."""
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
