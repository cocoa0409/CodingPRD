"""Hazardous material allowance: the two reporting bases and the MAQ boundary."""

from test_helpers import (
    AHJ_HEADERS,
    ApiErrorId,
    aggregate_allowance_gal,
    allowance_per_control_area_gal,
    approve_hazmat_permit,
    assert_money,
    assert_utilization_report,
    file_hazmat_permit,
    get_permit,
    get_utilization,
    setup_permitted_project,
    validate_error,
    validate_paginated,
)

NAMEPLATE = {
    "name": "Kendall Labs 400",
    "published_floor_to_floor_ft": 14.0,
    "published_live_load_psf": 95,
    "published_vibration_class": "VC_C",
    "exhaust_riser_capacity_cfm": 60000,
    "emergency_power_capacity_kw": 800,
    "chilled_water_capacity_tons": 1200,
}
SPRINKLERED_PLATE = {
    "floor_to_floor_ft": 14.0,
    "live_load_psf": 95,
    "vibration_class": "VC_C",
    "sprinklered": True,
}
DEMAND = {
    "required_vibration_class": "VC_C",
    "required_exhaust_cfm": 50000,
    "required_power_kw": 700,
    "measured_live_load_psf": 88,
}


def _qc_project_on_sprinklered_floor_two(api):
    """A permitted analytical QC project on a sprinklered second-floor plate."""
    return setup_permitted_project(
        api,
        allowance_psf=70.00,
        research_type="ANALYTICAL_QC",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=2000,
        lease_overrides={
            "base_rent_psf": 95.00,
            "delivery_deadline": "2026-12-31T00:00:00Z",
        },
        building_overrides=NAMEPLATE,
        floor_overrides={2: dict(SPRINKLERED_PLATE)},
        assessment_overrides=dict(DEMAND),
        project_overrides={"design_exhaust_cfm": 12000, "design_power_kw": 180},
    )


def test_report_denominators_come_from_the_plate_not_from_the_applications(api):
    """Both denominators are fixed by the plate and the hazard class alone.

    A sprinklered second-floor plate is entitled to three control areas at
    three quarters of the base flammable quantity, so the per-control-area
    allowance is 180.00 gallons and the whole-floor allowance is three times
    that, whatever the applications on the plate happen to ask for.

    Design: Difficulty/dual_variant_calc/hazmat_per_control_area_vs_aggregate_floor_basis
    """
    bundle = _qc_project_on_sprinklered_floor_two(api)
    floor = bundle["premises_floor"]
    tenant_headers = bundle["tenant_headers"]

    approved = file_hazmat_permit(
        api,
        bundle["project"]["id"],
        floor["id"],
        "FLAMMABLE_IB",
        "CLOSED_SYSTEM_USE",
        150.00,
        1,
        headers=tenant_headers,
    )
    approve_hazmat_permit(api, approved["id"])

    report = get_utilization(api, floor["id"], "FLAMMABLE_IB", 1, headers=AHJ_HEADERS)
    assert_utilization_report(report, floor["id"], "FLAMMABLE_IB")
    assert report["control_areas_allowed"] == 3
    assert_money(
        report["allowance_per_control_area_gal"],
        allowance_per_control_area_gal("FLAMMABLE_IB", 2, True, "CLOSED_SYSTEM_USE"),
        "allowance_per_control_area_gal",
    )
    assert_money(report["allowance_per_control_area_gal"], 180.00, "per control area")
    assert_money(
        report["aggregate_allowance_gal"],
        aggregate_allowance_gal("FLAMMABLE_IB", 2, True, "CLOSED_SYSTEM_USE"),
        "aggregate_allowance_gal",
    )
    assert_money(report["aggregate_allowance_gal"], 540.00, "whole floor")


def test_the_two_bases_disagree_because_only_one_of_them_counts_a_pending_row(api):
    """A pending application occupies the control area but not the whole floor.

    With 150.00 gallons approved and a further 20.00 gallons still awaiting a
    ruling in the same control area, the per-control-area basis is 170.00 while
    the whole-floor basis is only the approved 150.00, and the two percentages
    disagree accordingly.

    Design: Difficulty/dual_variant_calc/hazmat_per_control_area_vs_aggregate_floor_basis
    """
    bundle = _qc_project_on_sprinklered_floor_two(api)
    floor = bundle["premises_floor"]
    project_id = bundle["project"]["id"]
    tenant_headers = bundle["tenant_headers"]

    approved = file_hazmat_permit(
        api, project_id, floor["id"], "FLAMMABLE_IB", "CLOSED_SYSTEM_USE",
        150.00, 1, headers=tenant_headers,
    )
    approve_hazmat_permit(api, approved["id"])
    pending = file_hazmat_permit(
        api, project_id, floor["id"], "FLAMMABLE_IB", "CLOSED_SYSTEM_USE",
        20.00, 1, headers=tenant_headers,
    )

    assert get_permit(api, approved["id"])["status"] == "APPROVED"
    assert get_permit(api, pending["id"])["status"] == "REQUESTED"

    report = get_utilization(api, floor["id"], "FLAMMABLE_IB", 1, headers=AHJ_HEADERS)
    assert_money(report["per_control_area_basis_gal"], 170.00, "control area basis")
    assert_money(report["per_control_area_utilization_pct"], 94.44, "control area pct")
    assert_money(report["aggregate_basis_gal"], 150.00, "whole floor basis")
    assert_money(report["aggregate_utilization_pct"], 27.78, "whole floor pct")
    assert (
        report["per_control_area_basis_gal"] > report["aggregate_basis_gal"]
    ), "the pending row is counted on one basis and ignored on the other"


def test_a_request_for_exactly_the_allowance_is_created(api):
    """The comparison is strictly greater than, so the boundary itself is admissible.

    An application for exactly 180.00 gallons in a fresh control area sits on
    the allowance rather than above it and is accepted.

    Design: Difficulty/boundary_precision_check/hazmat_maq_boundary_180_00_accepted_180_01_rejected
    """
    bundle = _qc_project_on_sprinklered_floor_two(api)
    floor = bundle["premises_floor"]
    assert floor["control_areas_allowed"] == 3

    permit = file_hazmat_permit(
        api,
        bundle["project"]["id"],
        floor["id"],
        "FLAMMABLE_IB",
        "CLOSED_SYSTEM_USE",
        180.00,
        3,
        headers=bundle["tenant_headers"],
    )

    assert permit["status"] == "REQUESTED"
    assert_money(permit["quantity_gal"], 180.00, "quantity_gal")
    assert permit["control_area_index"] == 3
    assert_money(
        permit["allowance_per_control_area_gal"], 180.00, "allowance_per_control_area_gal"
    )


def test_one_hundredth_of_a_gallon_above_the_allowance_is_refused(api):
    """A hundredth of a gallon over the allowance is over the allowance.

    An application for 180.01 gallons in an otherwise empty control area is
    refused, so the test cannot have been rounded to whole gallons, and the
    refusal leaves the earlier admissible application as the project's only
    permit.

    Design: Difficulty/boundary_precision_check/hazmat_maq_boundary_180_00_accepted_180_01_rejected
    """
    bundle = _qc_project_on_sprinklered_floor_two(api)
    floor = bundle["premises_floor"]
    project_id = bundle["project"]["id"]
    tenant_headers = bundle["tenant_headers"]

    file_hazmat_permit(
        api, project_id, floor["id"], "FLAMMABLE_IB", "CLOSED_SYSTEM_USE",
        180.00, 3, headers=tenant_headers,
    )
    response = api.create_hazmat_permit(
        {
            "project_id": project_id,
            "floor_id": floor["id"],
            "hazard_class": "FLAMMABLE_IB",
            "use_condition": "CLOSED_SYSTEM_USE",
            "quantity_gal": 180.01,
            "control_area_index": 2,
        },
        tenant_headers,
    )

    validate_error(response, ApiErrorId.ERR_CONTROL_AREA_MAQ_EXCEEDED.value, 409)
    rows, _ = validate_paginated(
        api.list_hazmat_permits(AHJ_HEADERS, {"project_id": project_id})
    )
    assert len(rows) == 1, "the refused application was not persisted"
