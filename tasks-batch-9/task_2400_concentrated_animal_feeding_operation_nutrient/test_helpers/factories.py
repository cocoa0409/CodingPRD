"""Payload factories.

Each factory returns a request body containing client-supplied input fields
only — never a server-derived field — with sane defaults that satisfy the
declared constraints. Keyword arguments override any default; passing
``None`` for an optional key removes it from the payload so the server's own
default applies.
"""

from typing import Optional

from .constants import LAGOON_1, NORTH_40, WILLOW_CREEK

_OMIT = object()


def _merge(base: dict, overrides: dict) -> dict:
    payload = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ---------------------------------------------------------------------------
# Operation
# ---------------------------------------------------------------------------
def operation_payload(**overrides) -> dict:
    """Willow Creek Dairy: 300 dairy cows, liquid handling, conservation plan."""
    return _merge(
        {
            "name": WILLOW_CREEK["name"],
            "county": WILLOW_CREEK["county"],
            "animal_type": WILLOW_CREEK["animal_type"],
            "head_count": WILLOW_CREEK["head_count"],
            "manure_handling": WILLOW_CREEK["manure_handling"],
            "open_lot_area_sqft": WILLOW_CREEK["open_lot_area_sqft"],
            "discharge_potential": WILLOW_CREEK["discharge_potential"],
            "has_conservation_plan": WILLOW_CREEK["has_conservation_plan"],
        },
        overrides,
    )


def operation_patch_payload(**overrides) -> dict:
    """Herd-profile patch body; supply only the keys under test."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# Hauler
# ---------------------------------------------------------------------------
def hauler_payload(**overrides) -> dict:
    return _merge(
        {
            "business_name": "Prairie Pumping LLC",
            "license_number": "MH-4417",
            "license_expires_on": "2027-12-31T00:00:00Z",
            "certified_applicator": True,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Permit
# ---------------------------------------------------------------------------
def permit_payload(operation_id: str, **overrides) -> dict:
    return _merge(
        {
            "operation_id": operation_id,
            "permit_type": "GENERAL",
            "effective_on": "2026-01-01T00:00:00Z",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Nutrient management plan
# ---------------------------------------------------------------------------
def plan_payload(
    operation_id: str,
    permit_id: str,
    expected_operation_version: Optional[int] = None,
    **overrides,
) -> dict:
    base = {
        "operation_id": operation_id,
        "permit_id": permit_id,
        "plan_year": 2026,
        "allowed_application_methods": ["INJECTION", "INCORPORATED_24H"],
        "winter_application_allowed": False,
    }
    if expected_operation_version is not None:
        base["expected_operation_version"] = expected_operation_version
    return _merge(base, overrides)


def plan_patch_payload(**overrides) -> dict:
    """Plan edit body; supply only the keys under test."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# Field
# ---------------------------------------------------------------------------
def field_payload(operation_id: str, **overrides) -> dict:
    """North 40: 42.5 acres, 150 ft to water, 4 % slope, 900 ft frontage."""
    return _merge(
        {
            "operation_id": operation_id,
            "field_name": NORTH_40["field_name"],
            "total_acres": NORTH_40["total_acres"],
            "distance_to_water_ft": NORTH_40["distance_to_water_ft"],
            "has_tile_inlet": NORTH_40["has_tile_inlet"],
            "slope_pct": NORTH_40["slope_pct"],
            "water_frontage_ft": NORTH_40["water_frontage_ft"],
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Soil test
# ---------------------------------------------------------------------------
def soil_test_payload(field_id: str, **overrides) -> dict:
    """42 ppm phosphorus, which lands the index in the MEDIUM band."""
    return _merge(
        {
            "field_id": field_id,
            "sampled_on": "2026-03-15T00:00:00Z",
            "lab_name": "AgriLab",
            "soil_test_p_ppm": 42,
            "soil_test_k_ppm": 160,
            "organic_matter_pct": 3.4,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Field nutrient budget
# ---------------------------------------------------------------------------
def budget_payload(plan_id: str, field_id: str, soil_test_id: str, **overrides) -> dict:
    """Corn grain after soybean, injected: nitrogen-bound on a MEDIUM index."""
    return _merge(
        {
            "plan_id": plan_id,
            "field_id": field_id,
            "soil_test_id": soil_test_id,
            "crop": "CORN_GRAIN",
            "yield_goal": 190,
            "previous_crop": "SOYBEAN",
            "planned_application_method": "INJECTION",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Manure storage
# ---------------------------------------------------------------------------
def storage_payload(operation_id: str, **overrides) -> dict:
    """Lagoon 1: 60,000 sq ft by 144 in deep, 24 in freeboard."""
    return _merge(
        {
            "operation_id": operation_id,
            "structure_name": LAGOON_1["structure_name"],
            "structure_type": LAGOON_1["structure_type"],
            "surface_area_sqft": LAGOON_1["surface_area_sqft"],
            "total_depth_in": LAGOON_1["total_depth_in"],
            "required_freeboard_in": LAGOON_1["required_freeboard_in"],
        },
        overrides,
    )


def intake_payload(gallons: float = 1000000, **overrides) -> dict:
    return _merge({"gallons": gallons}, overrides)


# ---------------------------------------------------------------------------
# Storage inspection
# ---------------------------------------------------------------------------
def storage_inspection_payload(storage_id: str, **overrides) -> dict:
    return _merge(
        {
            "storage_id": storage_id,
            "inspected_on": "2026-07-25T00:00:00Z",
            "inspector_name": "R. Ames",
            "measured_freeboard_in": 30,
            "visual_condition": "NORMAL",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Land application event
# ---------------------------------------------------------------------------
def application_event_payload(
    plan_id: str, budget_id: str, storage_id: str, **overrides
) -> dict:
    """A dry-ground injection well inside every safeguard."""
    return _merge(
        {
            "plan_id": plan_id,
            "budget_id": budget_id,
            "storage_id": storage_id,
            "applied_on": "2026-07-05T00:00:00Z",
            "gallons_applied": 300000,
            "acres_treated": 30,
            "application_method": "INJECTION",
            "setback_maintained_ft": 60,
            "soil_condition": "DRY",
            "precipitation_forecast_in_24h": 0,
            "applicator_name": "J. Devlin",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Manure transfer
# ---------------------------------------------------------------------------
def transfer_payload(
    operation_id: str, storage_id: str, hauler_id: str, **overrides
) -> dict:
    return _merge(
        {
            "operation_id": operation_id,
            "storage_id": storage_id,
            "hauler_id": hauler_id,
            "recipient_name": "Hollis Row Crops",
            "recipient_address": "1420 County Road E, Linn",
            "transferred_on": "2026-07-10T00:00:00Z",
            "gallons_transferred": 200000,
            "nutrient_analysis_provided": True,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Incident report
# ---------------------------------------------------------------------------
def incident_payload(operation_id: str, **overrides) -> dict:
    """A discharge that reached water, so oral notification is required."""
    return _merge(
        {
            "operation_id": operation_id,
            "incident_type": "DISCHARGE",
            "discovered_at": "2026-08-01T00:00:00Z",
            "description": "Overflow at the transfer pump discharged to the tile outlet.",
            "released_gallons": 1500,
            "reached_water": True,
        },
        overrides,
    )


def mortality_incident_payload(operation_id: str, **overrides) -> dict:
    """A mortality event below the reportable threshold."""
    return _merge(
        {
            "operation_id": operation_id,
            "incident_type": "MORTALITY",
            "discovered_at": "2026-08-01T00:00:00Z",
            "description": "Two animals lost overnight; composted on site.",
            "mortality_head_count": 2,
            "disposal_method": "COMPOSTING",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Agency inspection
# ---------------------------------------------------------------------------
def inspection_payload(operation_id: str, permit_id: str, **overrides) -> dict:
    return _merge(
        {
            "operation_id": operation_id,
            "permit_id": permit_id,
            "scheduled_on": "2026-08-01T00:00:00Z",
            "inspection_kind": "ROUTINE",
        },
        overrides,
    )


def conduct_payload(findings_count: int = 1, **overrides) -> dict:
    base = {"findings_count": findings_count}
    if findings_count >= 1:
        base["deficiency_categories"] = ["RECORDKEEPING"]
    return _merge(base, overrides)


def inspection_response_payload(**overrides) -> dict:
    return _merge(
        {
            "corrective_action_summary": (
                "Recordkeeping binder rebuilt and staff retrained on log entry."
            )
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Annual report
# ---------------------------------------------------------------------------
def annual_report_payload(operation_id: str, plan_id: str, **overrides) -> dict:
    return _merge(
        {
            "operation_id": operation_id,
            "plan_id": plan_id,
            "report_year": 2026,
            "beginning_storage_gallons": 1000000,
            "ending_storage_gallons": 4374298,
        },
        overrides,
    )


def report_return_payload(**overrides) -> dict:
    return _merge(
        {"return_reason": "Ending storage figure does not match the inspection record."},
        overrides,
    )
