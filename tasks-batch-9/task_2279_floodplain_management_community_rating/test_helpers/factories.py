"""Payload factories — one per entity, input fields only.

Every factory accepts **overrides so a test can pin exactly the field it is
exercising and let the factory supply the rest.
"""
import itertools

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short discriminator for values the PRD requires to be unique."""
    return str(next(_counter)).zfill(4)


DEFAULTS = {
    "COMMUNITY_NAME": "Bayou City",
    "STATE_CODE": "TX",
    "FREEBOARD_FT": 1.0,
    "CUMULATIVE_PERIOD_YEARS": 10,
    "PANEL_NUMBER": "48001C0100",
    "SUFFIX": "H",
    "FLOOD_ZONE": "AE",
    "BASE_FLOOD_ELEVATION_FT": 12.0,
    "EFFECTIVE_DATE": "2020-01-01T00:00:00Z",
    "MAPPED_AREA_CODE": "RLA-1",
    "OWNER_NAME": "A Owner",
    "OWNER_EMAIL": "a@example.com",
    "MARKET_VALUE_USD": 200_000.00,
    "HIGHEST_ADJACENT_GRADE_FT": 10.0,
    "CONSTRUCTION_YEAR": 1998,
    "BOUNDARY_DESCRIPTION": "Blocks along the bayou",
    "REQUIRED_ACTION": "Elevate the lowest floor",
}


def create_community_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["COMMUNITY_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "cid_number": f"48{unique_suffix()}",
    }
    payload.update(overrides)
    return payload


def amend_community_payload(**overrides) -> dict:
    """PATCH body: freeboard_ft, cumulative_period_years, or both."""
    return dict(overrides)


def file_firm_panel_payload(community_id, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "panel_number": DEFAULTS["PANEL_NUMBER"],
        "suffix": DEFAULTS["SUFFIX"],
        "flood_zone": DEFAULTS["FLOOD_ZONE"],
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
        "base_flood_elevation_ft": DEFAULTS["BASE_FLOOD_ELEVATION_FT"],
    }
    payload.update(overrides)
    return payload


def create_property_payload(community_id, firm_panel_id, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "firm_panel_id": firm_panel_id,
        "parcel_id": f"P-{unique_suffix()}",
        "mapped_area_code": DEFAULTS["MAPPED_AREA_CODE"],
        "owner_name": DEFAULTS["OWNER_NAME"],
        "owner_email": DEFAULTS["OWNER_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_structure_payload(property_id, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "structure_use": "RESIDENTIAL",
        "pre_firm": False,
        "construction_year": DEFAULTS["CONSTRUCTION_YEAR"],
        "market_value_usd": DEFAULTS["MARKET_VALUE_USD"],
        "highest_adjacent_grade_ft": DEFAULTS["HIGHEST_ADJACENT_GRADE_FT"],
    }
    payload.update(overrides)
    return payload


def create_permit_payload(property_id, structure_id, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "structure_id": structure_id,
        "project_type": "NEW_CONSTRUCTION",
        "declared_project_cost_usd": 50_000.00,
        "proposed_lowest_floor_elevation_ft": 20.0,
    }
    payload.update(overrides)
    return payload


def submit_permit_payload(**overrides) -> dict:
    """A submission may optionally revise the three application values."""
    return dict(overrides)


def review_permit_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def file_certificate_payload(permit_id, structure_id, **overrides) -> dict:
    payload = {
        "permit_id": permit_id,
        "structure_id": structure_id,
        "certificate_type": "FINISHED_CONSTRUCTION",
        "datum": "NAVD88",
        "measured_lowest_floor_ft": 20.0,
        "measured_bfe_ft": 12.0,
        "surveyor_license_no": "TX-12345",
    }
    payload.update(overrides)
    return payload


def review_certificate_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def amend_certificate_payload(**overrides) -> dict:
    payload = {
        "datum": "NAVD88",
        "measured_lowest_floor_ft": 20.0,
        "measured_bfe_ft": 12.0,
        "surveyor_license_no": "TX-12345",
    }
    payload.update(overrides)
    return payload


def improvement_record_payload(structure_id, **overrides) -> dict:
    payload = {
        "structure_id": structure_id,
        "record_type": "IMPROVEMENT",
        "event_date": "2026-03-01T00:00:00Z",
        "cost_usd": 60_000.00,
    }
    payload.update(overrides)
    return payload


def reversal_record_payload(structure_id, reverses_record_id, **overrides) -> dict:
    payload = {
        "structure_id": structure_id,
        "record_type": "REVERSAL",
        "event_date": "2026-03-01T00:00:00Z",
        "reverses_record_id": reverses_record_id,
    }
    payload.update(overrides)
    return payload


def determination_case_payload(structure_id, expected_structure_version, **overrides) -> dict:
    payload = {
        "structure_id": structure_id,
        "method": "CUMULATIVE",
        "expected_structure_version": expected_structure_version,
    }
    payload.update(overrides)
    return payload


def inspection_sweep_payload(**overrides) -> dict:
    payload = {
        "declaration_code": f"DR-{unique_suffix()}",
        "event_date": "2026-07-01T00:00:00Z",
        "inspection_window_days": 30,
    }
    payload.update(overrides)
    return payload


def assess_inspection_payload(damage_cost_usd, **overrides) -> dict:
    payload = {"damage_cost_usd": damage_cost_usd}
    payload.update(overrides)
    return payload


def create_violation_payload(property_id, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "violation_type": "NO_PERMIT",
        "severity": "MAJOR",
    }
    payload.update(overrides)
    return payload


def create_remediation_order_payload(violation_id, deadline_at, **overrides) -> dict:
    payload = {
        "violation_id": violation_id,
        "required_action": DEFAULTS["REQUIRED_ACTION"],
        "deadline_at": deadline_at,
    }
    payload.update(overrides)
    return payload


def create_loss_area_payload(community_id, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "area_code": DEFAULTS["MAPPED_AREA_CODE"],
        "boundary_description": DEFAULTS["BOUNDARY_DESCRIPTION"],
    }
    payload.update(overrides)
    return payload


def launch_outreach_payload(crs_cycle_id, target_property_count, **overrides) -> dict:
    payload = {
        "crs_cycle_id": crs_cycle_id,
        "target_property_count": target_property_count,
    }
    payload.update(overrides)
    return payload


def higher_standard_payload(community_id, expected_community_version, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "activity_code": "A430_FREEBOARD",
        "documentation_cycle_year": 2026,
        "claimed_points": 100,
        "expected_community_version": expected_community_version,
    }
    payload.update(overrides)
    return payload


def verify_higher_standard_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_crs_cycle_payload(community_id, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "cycle_year": 2026,
        "cycle_start_date": "2026-01-01T00:00:00Z",
        "cycle_end_date": "2026-12-31T00:00:00Z",
        "due_at": "2026-12-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload
